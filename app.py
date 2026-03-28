import os
import streamlit as st
from dotenv import load_dotenv
from langchain_ollama import OllamaLLM, OllamaEmbeddings
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_community.vectorstores.utils import DistanceStrategy
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough
import oracledb
from ingest_v2 import ingest_file

load_dotenv()

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Local RAG Assistant",
    page_icon="🔍",
    layout="wide"
)

# ---------------------------------------------------------------------------
# Oracle connection (cached so it's reused across reruns)
# ---------------------------------------------------------------------------
@st.cache_resource
def get_connection():
    return oracledb.connect(
        user=os.getenv('ORACLE_USER'),
        password=os.getenv('ORACLE_PASSWORD'),
        dsn=os.getenv('ORACLE_DSN')
    )

@st.cache_resource
def get_vector_store(_conn):
    embeddings = OllamaEmbeddings(model='nomic-embed-text')
    return OracleVS(
        client=_conn,
        embedding_function=embeddings,
        table_name='RAG_DOCUMENTS',
        distance_strategy=DistanceStrategy.COSINE
    )

@st.cache_resource
def get_llm():
    return OllamaLLM(model='llama3.2', temperature=0, top_p=0.9)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []

# ---------------------------------------------------------------------------
# Helper: fetch list of ingested files from Oracle
# ---------------------------------------------------------------------------
def get_ingested_docs(conn):
    try:
        cursor = conn.cursor()
        cursor.execute('SELECT filename FROM ingested_files ORDER BY ingested_at DESC')
        return [row[0] for row in cursor.fetchall()]
    except Exception:
        return []

# ---------------------------------------------------------------------------
# Helper: format last 10 exchanges for the prompt
# ---------------------------------------------------------------------------
def format_history(history):
    if not history:
        return "No previous conversation."
    lines = []
    for turn in history[-10:]:
        lines.append(f"User: {turn['question']}")
        lines.append(f"Assistant: {turn['answer']}")
    return "\n".join(lines)

# ---------------------------------------------------------------------------
# Helper: format retrieved docs
# ---------------------------------------------------------------------------
def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

# ---------------------------------------------------------------------------
# Build the RAG chain
# ---------------------------------------------------------------------------
def build_chain(vector_store, llm):
    prompt_template = PromptTemplate.from_template('''
You are a precise assistant that answers questions strictly from the provided context.

Rules:
- Use ONLY the information in the context below. Do not use any prior knowledge.
- If the answer is not explicitly stated in the context, respond with:
  "I could not find that in the provided documents."
- Do not infer, assume, or extrapolate beyond what is written.
- Use the conversation history to resolve follow-up questions and pronouns.

Conversation so far:
{history}

Context from documents:
{context}

Question: {question}

Answer:''')

    retriever = vector_store.as_retriever(search_kwargs={'k': 8})

    chain = (
        {
            "context": retriever | format_docs,
            "question": RunnablePassthrough(),
            "history": lambda _: format_history(st.session_state.chat_history)
        }
        | prompt_template
        | llm
        | StrOutputParser()
    )
    return chain, retriever

# ---------------------------------------------------------------------------
# Ask a question
# ---------------------------------------------------------------------------
def ask(question, chain, retriever):
    answer = chain.invoke(question)
    docs = retriever.invoke(question)
    sources = sorted(set(
        os.path.basename(doc.metadata.get('source', 'unknown'))
        for doc in docs
    ))
    return answer, sources

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------
conn = get_connection()
vector_store = get_vector_store(conn)
llm = get_llm()
chain, retriever = build_chain(vector_store, llm)

# Sidebar
with st.sidebar:
    st.title("Local RAG Assistant")
    st.caption("Powered by Ollama + LangChain + Oracle 23ai")
    st.divider()

    # Document uploader
    st.subheader("Upload a document")
    uploaded = st.file_uploader(
        "Supported: .txt .md .pdf .docx",
        type=['txt', 'md', 'pdf', 'docx'],
        label_visibility="collapsed"
    )
    if uploaded:
        save_path = os.path.join('docs', uploaded.name)
        os.makedirs('docs', exist_ok=True)
        with open(save_path, 'wb') as f:
            f.write(uploaded.read())
        with st.spinner(f'Ingesting {uploaded.name}...'):
            result = ingest_file(save_path, conn)
        if result == 'ingested':
            st.success(f"Ingested: {uploaded.name}")
            st.cache_resource.clear()
        elif result == 'duplicate':
            st.info(f"{uploaded.name} is already in the knowledge base.")
        else:
            st.error(f"Failed to ingest {uploaded.name}")

    st.divider()

    # Ingested documents list
    st.subheader("Knowledge base")
    docs = get_ingested_docs(conn)
    if docs:
        for doc in docs:
            st.text(f"  {os.path.basename(doc)}")
    else:
        st.caption("No documents ingested yet.")

    st.divider()

    # Clear conversation
    if st.button("Clear conversation", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()

    st.caption(f"Memory: last {min(len(st.session_state.chat_history), 10)} of {len(st.session_state.chat_history)} exchanges")

# Main panel
st.title("Ask your documents")

# Display chat history
for turn in st.session_state.chat_history:
    with st.chat_message("user"):
        st.write(turn['question'])
    with st.chat_message("assistant"):
        st.write(turn['answer'])
        if turn['sources']:
            st.caption(f"Sources: {', '.join(turn['sources'])}")

# Chat input
if question := st.chat_input("Ask a question about your documents..."):
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            answer, sources = ask(question, chain, retriever)
        st.write(answer)
        if sources:
            st.caption(f"Sources: {', '.join(sources)}")

    st.session_state.chat_history.append({
        'question': question,
        'answer': answer,
        'sources': sources
    })
