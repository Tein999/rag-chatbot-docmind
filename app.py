# import os
# from dotenv import load_dotenv
# load_dotenv()
# from flask import Flask, render_template, request, jsonify
# from werkzeug.utils import secure_filename
# import PyPDF2
# from openai import OpenAI, AuthenticationError, RateLimitError, APIError

# app = Flask(__name__)
# app.config['UPLOAD_FOLDER'] = 'uploads'
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# api_key = os.getenv("OPENAI_API_KEY", "").strip()
# client = OpenAI(api_key=api_key) if api_key else None

# # In-memory document store (replace with ChromaDB/Pinecone for production)
# document_store = {}
# chat_history = []

# ALLOWED_EXTENSIONS = {'pdf', 'txt'}

# def allowed_file(filename):
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# def extract_text_from_pdf(filepath):
#     text = ""
#     with open(filepath, 'rb') as f:
#         reader = PyPDF2.PdfReader(f)
#         for page in reader.pages:
#             page_text = page.extract_text()
#             if page_text:
#                 text += page_text + "\n"
#     return text

# def extract_text_from_txt(filepath):
#     with open(filepath, 'r', encoding='utf-8') as f:
#         return f.read()

# def chunk_text(text, chunk_size=1000, overlap=200):
#     """Split text into overlapping chunks for better context retrieval."""
#     chunks = []
#     start = 0
#     while start < len(text):
#         end = start + chunk_size
#         chunk = text[start:end]
#         chunks.append(chunk)
#         start += chunk_size - overlap
#     return chunks

# def get_relevant_chunks(query, chunks, top_k=3):
#     """Simple keyword-based retrieval (replace with embeddings for production)."""
#     query_words = set(query.lower().split())
#     scored_chunks = []
#     for i, chunk in enumerate(chunks):
#         chunk_words = set(chunk.lower().split())
#         score = len(query_words.intersection(chunk_words))
#         scored_chunks.append((score, i, chunk))
#     scored_chunks.sort(reverse=True)
#     return [chunk for _, _, chunk in scored_chunks[:top_k]]

# def local_answer(user_message, context, sources):
#     """Extractive fallback when OpenAI is unavailable (no key / no credits)."""
#     if not context.strip():
#         return (
#             "No documents are loaded yet. Upload a PDF or TXT file first, "
#             "then ask your question again."
#         )

#     summary_words = {"summary", "summarize", "summarise", "overview", "brief"}
#     wants_summary = any(word in user_message.lower() for word in summary_words)

#     if wants_summary:
#         # Prefer opening chunks for document overview
#         opener = []
#         for chunks in document_store.values():
#             opener.extend(chunks[:2])
#         body = "\n\n".join(opener)[:2500]
#         return (
#             f"Here's an extractive summary from your document(s) "
#             f"({', '.join(sources)}):\n\n{body}"
#         )

#     return (
#         f"Based on your documents ({', '.join(sources)}), here are the most "
#         f"relevant excerpts:\n\n{context}"
#     )

# @app.route('/')
# def index():
#     return render_template('index.html')

# @app.route('/upload', methods=['POST'])
# def upload_file():
#     if 'file' not in request.files:
#         return jsonify({'error': 'No file provided'}), 400
    
#     file = request.files['file']
#     if file.filename == '':
#         return jsonify({'error': 'No file selected'}), 400
    
#     if not allowed_file(file.filename):
#         return jsonify({'error': 'Only PDF and TXT files allowed'}), 400

#     filename = secure_filename(file.filename)
#     filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     file.save(filepath)

#     # Extract text
#     if filename.endswith('.pdf'):
#         text = extract_text_from_pdf(filepath)
#     else:
#         text = extract_text_from_txt(filepath)

#     # Chunk and store
#     chunks = chunk_text(text)
#     document_store[filename] = chunks

#     return jsonify({
#         'success': True,
#         'filename': filename,
#         'chunks': len(chunks),
#         'preview': text[:300] + '...' if len(text) > 300 else text
#     })

# @app.route('/chat', methods=['POST'])
# def chat():
#     data = request.json
#     user_message = data.get('message', '').strip()
    
#     if not user_message:
#         return jsonify({'error': 'Empty message'}), 400

#     sources = list(document_store.keys())

#     # Build context from all uploaded documents
#     context = ""
#     if document_store:
#         all_chunks = []
#         for chunks in document_store.values():
#             all_chunks.extend(chunks)
#         relevant_chunks = get_relevant_chunks(user_message, all_chunks)
#         context = "\n\n".join(relevant_chunks)

#     # Build messages for OpenAI
#     system_prompt = """You are a helpful document assistant. Answer questions based on the provided document context.
# If the answer is not in the context, say so clearly. Be concise and accurate."""

#     messages = [{"role": "system", "content": system_prompt}]
    
#     if context:
#         messages.append({
#             "role": "user",
#             "content": f"Document context:\n{context}\n\nQuestion: {user_message}"
#         })
#     else:
#         messages.append({
#             "role": "user", 
#             "content": f"{user_message}\n\n(No documents uploaded yet. Please upload a PDF or TXT file first.)"
#         })

#     # Add recent chat history
#     for msg in chat_history[-6:]:
#         messages.insert(-1, msg)

#     assistant_message = None
#     used_fallback = False

#     if client is None:
#         assistant_message = local_answer(user_message, context, sources)
#         used_fallback = True
#     else:
#         try:
#             response = client.chat.completions.create(
#                 model="gpt-3.5-turbo",
#                 messages=messages,
#                 max_tokens=500,
#                 temperature=0.3
#             )
#             assistant_message = response.choices[0].message.content
#         except AuthenticationError:
#             assistant_message = (
#                 local_answer(user_message, context, sources)
#                 + "\n\n---\nNote: OpenAI API key is invalid. Using local extractive answers. "
#                 "Update OPENAI_API_KEY in your .env file."
#             )
#             used_fallback = True
#         except RateLimitError:
#             assistant_message = (
#                 local_answer(user_message, context, sources)
#                 + "\n\n---\nNote: OpenAI quota/credits are exhausted. Using local extractive answers. "
#                 "Add credits at https://platform.openai.com/settings/organization/billing/"
#             )
#             used_fallback = True
#         except APIError as e:
#             assistant_message = (
#                 local_answer(user_message, context, sources)
#                 + f"\n\n---\nNote: OpenAI API error ({e.__class__.__name__}). "
#                 "Using local extractive answers."
#             )
#             used_fallback = True
#         except Exception as e:
#             return jsonify({
#                 'error': f'Chat failed: {type(e).__name__}: {e}'
#             }), 500

#     # Update history
#     chat_history.append({"role": "user", "content": user_message})
#     chat_history.append({"role": "assistant", "content": assistant_message})

#     return jsonify({
#         'response': assistant_message,
#         'sources': sources,
#         'fallback': used_fallback
#     })

# @app.route('/clear', methods=['POST'])
# def clear():
#     global chat_history
#     chat_history = []
#     document_store.clear()
#     return jsonify({'success': True})

# if __name__ == '__main__':
#     os.makedirs('uploads', exist_ok=True)
#     app.run(debug=True, port=5000)


# import os
# import re
# from dotenv import load_dotenv
# load_dotenv(override=True)  # .env wins over stale terminal variables
# from flask import Flask, render_template, request, jsonify
# from werkzeug.utils import secure_filename
# import PyPDF2
# from openai import OpenAI, AuthenticationError, RateLimitError, APIError

# app = Flask(__name__)
# app.config['UPLOAD_FOLDER'] = 'uploads'
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# api_key = os.getenv("OPENAI_API_KEY", "").strip()
# MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
# client = OpenAI(api_key=api_key) if api_key else None

# document_store = {}    # filename -> chunks (for question answering)
# full_text_store = {}   # filename -> full text (for summaries)
# chat_history = []

# ALLOWED_EXTENSIONS = {'pdf', 'txt'}
# STOPWORDS = {"the", "a", "an", "of", "to", "in", "is", "are", "me", "give", "what",
#              "which", "this", "that", "and", "or", "for", "on", "it", "about",
#              "from", "with", "tell", "uploaded", "file", "document", "pdf"}


# def allowed_file(filename):
#     return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


# def extract_text_from_pdf(filepath):
#     text = ""
#     with open(filepath, 'rb') as f:
#         reader = PyPDF2.PdfReader(f)
#         for page in reader.pages:
#             page_text = page.extract_text()
#             if page_text:
#                 text += page_text + "\n"
#     return text


# def extract_text_from_txt(filepath):
#     with open(filepath, 'r', encoding='utf-8') as f:
#         return f.read()


# def chunk_text(text, chunk_size=1000, overlap=200):
#     chunks, start = [], 0
#     while start < len(text):
#         chunks.append(text[start:start + chunk_size])
#         start += chunk_size - overlap
#     return chunks


# def get_relevant_chunks(query, chunks, top_k=4):
#     """Keyword retrieval that ignores filler words."""
#     query_words = {w for w in re.findall(r"\w+", query.lower())
#                    if w not in STOPWORDS and len(w) > 2}
#     scored = []
#     for i, chunk in enumerate(chunks):
#         chunk_words = set(re.findall(r"\w+", chunk.lower()))
#         scored.append((len(query_words & chunk_words), i, chunk))
#     scored.sort(key=lambda x: (-x[0], x[1]))
#     return [c for _, _, c in scored[:top_k]]


# def is_summary_request(q):
#     q = q.lower()
#     return any(k in q for k in ["summary", "summarize", "summarise", "overview",
#                                 "what is this document about", "what is the document about"])


# def ask_llm(messages, max_tokens=500):
#     r = client.chat.completions.create(
#         model="gpt-4o-mini", messages=messages,
#         max_tokens=max_tokens, temperature=0.3)
#     return r.choices[0].message.content


# def summarize_all(texts, section_size=12000):
#     """Map-reduce: summarize each section, then combine the partial summaries."""
#     partials = []
#     for text in texts.values():
#         for i in range(0, len(text), section_size):
#             partials.append(ask_llm([
#                 {"role": "system", "content": "Summarize the text in 4-5 concise bullet points."},
#                 {"role": "user", "content": text[i:i + section_size]}], max_tokens=300))
#     return ask_llm([
#         {"role": "system", "content": "Combine these partial summaries into one clear, "
#                                       "well-organized summary of the whole document."},
#         {"role": "user", "content": "\n".join(partials)}], max_tokens=600)


# def answer_question(question, context):
#     messages = [{"role": "system", "content":
#                  "You are a helpful document assistant. Answer using the provided document "
#                  "context. If the answer is not in the context, say so clearly. Be concise."}]
#     messages.extend(chat_history[-6:])
#     messages.append({"role": "user",
#                      "content": f"Document context:\n{context}\n\nQuestion: {question}"})
#     return ask_llm(messages)


# def local_answer(wants_summary, context):
#     """Last-resort fallback: raw excerpts, clearly labelled as non-AI."""
#     if wants_summary:
#         opener = []
#         for chunks in document_store.values():
#             opener.extend(chunks[:2])
#         return "\n\n".join(opener)[:2500]
#     return context


# @app.route('/')
# def index():
#     return render_template('index.html')


# @app.route('/upload', methods=['POST'])
# def upload_file():
#     if 'file' not in request.files:
#         return jsonify({'error': 'No file provided'}), 400
#     file = request.files['file']
#     if file.filename == '':
#         return jsonify({'error': 'No file selected'}), 400
#     if not allowed_file(file.filename):
#         return jsonify({'error': 'Only PDF and TXT files allowed'}), 400

#     filename = secure_filename(file.filename)
#     filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
#     file.save(filepath)

#     text = (extract_text_from_pdf(filepath) if filename.endswith('.pdf')
#             else extract_text_from_txt(filepath))
#     if not text.strip():
#         return jsonify({'error': 'No readable text found. Scanned PDFs need OCR.'}), 400

#     full_text_store[filename] = text
#     chunks = chunk_text(text)
#     document_store[filename] = chunks

#     return jsonify({
#         'success': True,
#         'filename': filename,
#         'chunks': len(chunks),
#         'preview': text[:300] + '...' if len(text) > 300 else text
#     })


# @app.route('/chat', methods=['POST'])
# def chat():
#     data = request.get_json(silent=True) or {}
#     user_message = data.get('message', '').strip()
#     if not user_message:
#         return jsonify({'error': 'Empty message'}), 400
#     if not document_store:
#         return jsonify({'response': 'Upload a PDF or TXT file first, then ask your question.',
#                         'sources': [], 'fallback': False})

#     sources = list(document_store.keys())
#     wants_summary = is_summary_request(user_message)
#     all_chunks = [c for chunks in document_store.values() for c in chunks]
#     context = "\n\n".join(get_relevant_chunks(user_message, all_chunks))

#     note = None
#     if client is None:
#         note = "No OpenAI API key found. Add OPENAI_API_KEY to your .env file."
#     else:
#         try:
#             answer = (summarize_all(full_text_store) if wants_summary
#                       else answer_question(user_message, context))
#             chat_history.append({"role": "user", "content": user_message})
#             chat_history.append({"role": "assistant", "content": answer})
#             return jsonify({'response': answer, 'sources': sources, 'fallback': False})
#         except AuthenticationError:
#             note = "Your OpenAI API key is invalid or expired. Create a new key and update .env."
#         except RateLimitError:
#             note = "OpenAI quota exhausted or rate limit hit. Check billing credits."
#         except APIError as e:
#             note = f"OpenAI API error ({e.__class__.__name__})."
#         except Exception as e:
#             return jsonify({'error': f'Chat failed: {type(e).__name__}: {e}'}), 500

#     print("Fallback used:", note)
#     answer = (f"⚠️ {note}\n\nThis is NOT an AI answer. Showing raw excerpts from your document:\n\n"
#               + local_answer(wants_summary, context))
#     return jsonify({'response': answer, 'sources': sources, 'fallback': True})


# @app.route('/clear', methods=['POST'])
# def clear():
#     global chat_history
#     chat_history = []
#     document_store.clear()
#     full_text_store.clear()
#     return jsonify({'success': True})


# if __name__ == '__main__':
#     os.makedirs('uploads', exist_ok=True)
#     app.run(debug=True, port=5000)
import os
import re
import time
from dotenv import load_dotenv
load_dotenv(override=True)  # values in .env win over stale terminal variables
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import PyPDF2
from openai import (
    OpenAI,
    AuthenticationError,
    RateLimitError,
    NotFoundError,
    APIConnectionError,
    APIError,
)

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# ---------------------------------------------------------------------------
# LLM configuration (Groq free tier by default, all values come from .env)
# ---------------------------------------------------------------------------
API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
BASE_URL = os.getenv("OPENAI_BASE_URL", "").strip() or "https://api.groq.com/openai/v1"
MODEL = os.getenv("OPENAI_MODEL", "").strip() or "openai/gpt-oss-20b"

client = OpenAI(api_key=API_KEY, base_url=BASE_URL) if API_KEY else None

# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------
document_store = {}    # filename -> list of chunks (question answering)
full_text_store = {}   # filename -> full text (summaries)
chat_history = []

ALLOWED_EXTENSIONS = {'pdf', 'txt'}
STOPWORDS = {
    "the", "a", "an", "of", "to", "in", "is", "are", "me", "give", "what",
    "which", "this", "that", "and", "or", "for", "on", "it", "about", "from",
    "with", "tell", "uploaded", "file", "document", "pdf",
}


# ---------------------------------------------------------------------------
# File handling
# ---------------------------------------------------------------------------
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_pdf(filepath):
    text = ""
    with open(filepath, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
    return text


def extract_text_from_txt(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return f.read()


def chunk_text(text, chunk_size=1000, overlap=200):
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + chunk_size])
        start += chunk_size - overlap
    return chunks


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def get_relevant_chunks(query, chunks, top_k=4):
    """Keyword retrieval that ignores filler words."""
    query_words = {
        w for w in re.findall(r"\w+", query.lower())
        if w not in STOPWORDS and len(w) > 2
    }
    scored = []
    for i, chunk in enumerate(chunks):
        chunk_words = set(re.findall(r"\w+", chunk.lower()))
        scored.append((len(query_words & chunk_words), i, chunk))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _, _, c in scored[:top_k]]


def is_summary_request(q):
    q = q.lower()
    return any(k in q for k in [
        "summary", "summarize", "summarise", "overview",
        "what is this document about", "what is the document about",
    ])


# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------
def ask_llm(messages, max_tokens=500, retries=3):
    """Call the LLM. On a rate limit, wait and retry before giving up."""
    extra = {}
    if "gpt-oss" in MODEL or "qwen" in MODEL:
        # Reasoning models spend part of the token budget on thinking,
        # so leave extra room for the visible answer.
        max_tokens = max(max_tokens, 1500)
    if "gpt-oss" in MODEL:
        extra["extra_body"] = {"reasoning_effort": "low"}

    for attempt in range(retries):
        try:
            r = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                max_tokens=max_tokens,
                temperature=0.3,
                **extra,
            )
            content = r.choices[0].message.content or ""
            # Some models include <think>...</think>; hide it from the user.
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
            return content or "(The model returned no text. Please try again.)"
        except RateLimitError:
            if attempt == retries - 1:
                raise
            time.sleep(8 * (attempt + 1))  # 8s, then 16s


def summarize_all(texts, section_size=10000):
    """Map-reduce: summarize each section, then combine the partial summaries."""
    partials = []
    for text in texts.values():
        for i in range(0, len(text), section_size):
            partials.append(ask_llm([
                {"role": "system",
                 "content": "Summarize the text in 4-5 concise bullet points."},
                {"role": "user", "content": text[i:i + section_size]},
            ], max_tokens=300))
    return ask_llm([
        {"role": "system",
         "content": "Combine these partial summaries into one clear, "
                    "well-organized summary of the whole document."},
        {"role": "user", "content": "\n".join(partials)},
    ], max_tokens=700)


def answer_question(question, context):
    messages = [{
        "role": "system",
        "content": "You are a helpful document assistant. Answer using the "
                   "provided document context. If the answer is not in the "
                   "context, say so clearly. Be concise and accurate.",
    }]
    messages.extend(chat_history[-6:])
    messages.append({
        "role": "user",
        "content": f"Document context:\n{context}\n\nQuestion: {question}",
    })
    return ask_llm(messages)


def local_answer(wants_summary, context):
    """Last-resort fallback: raw excerpts, clearly labelled as non-AI."""
    if wants_summary:
        opener = []
        for chunks in document_store.values():
            opener.extend(chunks[:2])
        return "\n\n".join(opener)[:2500]
    return context


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': 'Only PDF and TXT files allowed'}), 400

    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)

    text = (extract_text_from_pdf(filepath) if filename.endswith('.pdf')
            else extract_text_from_txt(filepath))
    if not text.strip():
        return jsonify({
            'error': 'No readable text found. Scanned PDFs need OCR.'
        }), 400

    full_text_store[filename] = text
    chunks = chunk_text(text)
    document_store[filename] = chunks

    return jsonify({
        'success': True,
        'filename': filename,
        'chunks': len(chunks),
        'preview': text[:300] + '...' if len(text) > 300 else text,
    })


@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(silent=True) or {}
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': 'Empty message'}), 400
    if not document_store:
        return jsonify({
            'response': 'Upload a PDF or TXT file first, then ask your question.',
            'sources': [],
            'fallback': False,
        })

    sources = list(document_store.keys())
    wants_summary = is_summary_request(user_message)
    all_chunks = [c for chunks in document_store.values() for c in chunks]
    context = "\n\n".join(get_relevant_chunks(user_message, all_chunks))

    note = None
    if client is None:
        note = "No API key found. Add OPENAI_API_KEY to your .env file."
    else:
        try:
            answer = (summarize_all(full_text_store) if wants_summary
                      else answer_question(user_message, context))
            chat_history.append({"role": "user", "content": user_message})
            chat_history.append({"role": "assistant", "content": answer})
            return jsonify({'response': answer, 'sources': sources, 'fallback': False})
        except AuthenticationError:
            note = "Your API key is invalid or expired. Create a new key and update .env."
        except NotFoundError:
            note = (f"Model '{MODEL}' was not found. Pick another model from your "
                    "provider's model list and set OPENAI_MODEL in .env.")
        except RateLimitError:
            note = ("Rate limit reached on the free tier. Wait a minute and try again.")
        except APIConnectionError:
            note = "Could not reach the API. Check your internet connection."
        except APIError as e:
            note = f"API error ({e.__class__.__name__})."
        except Exception as e:
            return jsonify({'error': f'Chat failed: {type(e).__name__}: {e}'}), 500

    print("Fallback used:", note)
    answer = (f"⚠️ {note}\n\nThis is NOT an AI answer. "
              f"Showing raw excerpts from your document:\n\n"
              + local_answer(wants_summary, context))
    return jsonify({'response': answer, 'sources': sources, 'fallback': True})


@app.route('/clear', methods=['POST'])
def clear():
    global chat_history
    chat_history = []
    document_store.clear()
    full_text_store.clear()
    return jsonify({'success': True})


if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    print(f"Using model '{MODEL}' at {BASE_URL}")
    app.run(debug=True, port=5000)
