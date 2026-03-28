import os
from dotenv import load_dotenv
from langchain_community.document_loaders import (
    TextLoader, PyPDFLoader, Docx2txtLoader
)
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_community.vectorstores.oraclevs import OracleVS
from langchain_community.vectorstores.utils import DistanceStrategy
import oracledb

load_dotenv()

SUPPORTED_EXTENSIONS = {'txt', 'md', 'pdf', 'docx'}

# ---------------------------------------------------------------------------
# Load a single file using the appropriate loader
# ---------------------------------------------------------------------------
def load_file(fpath):
    ext = fpath.lower().split('.')[-1]
    if ext in ('txt', 'md'):
        return TextLoader(fpath).load()
    elif ext == 'pdf':
        return PyPDFLoader(fpath).load()
    elif ext == 'docx':
        return Docx2txtLoader(fpath).load()
    else:
        return []

# ---------------------------------------------------------------------------
# Load all supported files from a folder tree
# ---------------------------------------------------------------------------
def load_documents(folder='docs/'):
    all_docs = []
    for root, _, files in os.walk(folder):
        for fname in files:
            ext = fname.lower().split('.')[-1]
            if ext in SUPPORTED_EXTENSIONS:
                fpath = os.path.join(root, fname)
                try:
                    all_docs += load_file(fpath)
                except Exception as e:
                    print(f"  Warning: could not load {fpath}: {e}")
    return all_docs

# ---------------------------------------------------------------------------
# Ensure tracking and vector tables exist
# ---------------------------------------------------------------------------
def ensure_tables(conn):
    cursor = conn.cursor()
    conn.autocommit = True
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ingested_files (
            filename VARCHAR2(500) PRIMARY KEY,
            ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

# ---------------------------------------------------------------------------
# Ingest a single file — used by the Streamlit uploader
# Returns: 'ingested', 'duplicate', or 'error'
# ---------------------------------------------------------------------------
def ingest_file(fpath, conn):
    ensure_tables(conn)
    cursor = conn.cursor()
    norm = os.path.normpath(fpath)

    # Check for duplicate
    cursor.execute('SELECT COUNT(*) FROM ingested_files WHERE filename = :1', [norm])
    if cursor.fetchone()[0] > 0:
        return 'duplicate'

    try:
        docs = load_file(fpath)
        if not docs:
            return 'error'

        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_documents(docs)

        embeddings = OllamaEmbeddings(model='nomic-embed-text')

        # Check if RAG_DOCUMENTS exists
        cursor.execute("""
            SELECT COUNT(*) FROM user_tables WHERE table_name = 'RAG_DOCUMENTS'
        """)
        table_exists = cursor.fetchone()[0] > 0

        if table_exists:
            vector_store = OracleVS(
                client=conn,
                embedding_function=embeddings,
                table_name='RAG_DOCUMENTS',
                distance_strategy=DistanceStrategy.COSINE
            )
            vector_store.add_documents(chunks)
        else:
            OracleVS.from_documents(
                documents=chunks,
                embedding=embeddings,
                client=conn,
                table_name='RAG_DOCUMENTS',
                distance_strategy=DistanceStrategy.COSINE
            )

        cursor.execute(
            'INSERT INTO ingested_files (filename) VALUES (:1)', [norm]
        )
        return 'ingested'

    except Exception as e:
        print(f"Ingest error for {fpath}: {e}")
        return 'error'

# ---------------------------------------------------------------------------
# Bulk ingest — run from the command line to process the entire docs/ folder
# ---------------------------------------------------------------------------
def ingest_all(folder='docs/', conn=None):
    own_conn = conn is None
    if own_conn:
        conn = oracledb.connect(
            user=os.getenv('ORACLE_USER'),
            password=os.getenv('ORACLE_PASSWORD'),
            dsn=os.getenv('ORACLE_DSN')
        )

    ensure_tables(conn)
    cursor = conn.cursor()
    conn.autocommit = True

    cursor.execute('SELECT filename FROM ingested_files')
    already_done = {os.path.normpath(row[0]) for row in cursor.fetchall()}

    all_docs = load_documents(folder)
    print(f'Loader found: {len(all_docs)} document pages/sections')

    new_docs = [d for d in all_docs
                if os.path.normpath(d.metadata.get('source', '')) not in already_done]

    if not new_docs:
        print('No new documents to ingest.')
        return

    # Get unique new source files for tracking
    new_sources = list(dict.fromkeys(
        os.path.normpath(d.metadata.get('source', '')) for d in new_docs
    ))
    skipped = len(all_docs) - len(new_docs)
    print(f'Found {len(new_sources)} new file(s). Skipping {skipped} already ingested sections.')

    splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    chunks = splitter.split_documents(new_docs)
    print(f'Split into {len(chunks)} chunks')

    embeddings = OllamaEmbeddings(model='nomic-embed-text')

    cursor.execute("SELECT COUNT(*) FROM user_tables WHERE table_name = 'RAG_DOCUMENTS'")
    table_exists = cursor.fetchone()[0] > 0

    if table_exists:
        print('RAG_DOCUMENTS exists. Appending new chunks...')
        vector_store = OracleVS(
            client=conn,
            embedding_function=embeddings,
            table_name='RAG_DOCUMENTS',
            distance_strategy=DistanceStrategy.COSINE
        )
        vector_store.add_documents(chunks)
    else:
        print('Creating RAG_DOCUMENTS table for the first time...')
        OracleVS.from_documents(
            documents=chunks,
            embedding=embeddings,
            client=conn,
            table_name='RAG_DOCUMENTS',
            distance_strategy=DistanceStrategy.COSINE
        )

    for source in new_sources:
        cursor.execute(
            'INSERT INTO ingested_files (filename) VALUES (:1)', [source]
        )

    print('Ingestion complete. Vectors stored in Oracle.')

    if own_conn:
        conn.close()

if __name__ == '__main__':
    ingest_all()
