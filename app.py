import os
from dotenv import load_dotenv
load_dotenv()
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
import PyPDF2
from openai import OpenAI, AuthenticationError, RateLimitError, APIError

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

api_key = os.getenv("OPENAI_API_KEY", "").strip()
client = OpenAI(api_key=api_key) if api_key else None

# In-memory document store (replace with ChromaDB/Pinecone for production)
document_store = {}
chat_history = []

ALLOWED_EXTENSIONS = {'pdf', 'txt'}

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
    """Split text into overlapping chunks for better context retrieval."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks

def get_relevant_chunks(query, chunks, top_k=3):
    """Simple keyword-based retrieval (replace with embeddings for production)."""
    query_words = set(query.lower().split())
    scored_chunks = []
    for i, chunk in enumerate(chunks):
        chunk_words = set(chunk.lower().split())
        score = len(query_words.intersection(chunk_words))
        scored_chunks.append((score, i, chunk))
    scored_chunks.sort(reverse=True)
    return [chunk for _, _, chunk in scored_chunks[:top_k]]

def local_answer(user_message, context, sources):
    """Extractive fallback when OpenAI is unavailable (no key / no credits)."""
    if not context.strip():
        return (
            "No documents are loaded yet. Upload a PDF or TXT file first, "
            "then ask your question again."
        )

    summary_words = {"summary", "summarize", "summarise", "overview", "brief"}
    wants_summary = any(word in user_message.lower() for word in summary_words)

    if wants_summary:
        # Prefer opening chunks for document overview
        opener = []
        for chunks in document_store.values():
            opener.extend(chunks[:2])
        body = "\n\n".join(opener)[:2500]
        return (
            f"Here's an extractive summary from your document(s) "
            f"({', '.join(sources)}):\n\n{body}"
        )

    return (
        f"Based on your documents ({', '.join(sources)}), here are the most "
        f"relevant excerpts:\n\n{context}"
    )

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

    # Extract text
    if filename.endswith('.pdf'):
        text = extract_text_from_pdf(filepath)
    else:
        text = extract_text_from_txt(filepath)

    # Chunk and store
    chunks = chunk_text(text)
    document_store[filename] = chunks

    return jsonify({
        'success': True,
        'filename': filename,
        'chunks': len(chunks),
        'preview': text[:300] + '...' if len(text) > 300 else text
    })

@app.route('/chat', methods=['POST'])
def chat():
    data = request.json
    user_message = data.get('message', '').strip()
    
    if not user_message:
        return jsonify({'error': 'Empty message'}), 400

    sources = list(document_store.keys())

    # Build context from all uploaded documents
    context = ""
    if document_store:
        all_chunks = []
        for chunks in document_store.values():
            all_chunks.extend(chunks)
        relevant_chunks = get_relevant_chunks(user_message, all_chunks)
        context = "\n\n".join(relevant_chunks)

    # Build messages for OpenAI
    system_prompt = """You are a helpful document assistant. Answer questions based on the provided document context.
If the answer is not in the context, say so clearly. Be concise and accurate."""

    messages = [{"role": "system", "content": system_prompt}]
    
    if context:
        messages.append({
            "role": "user",
            "content": f"Document context:\n{context}\n\nQuestion: {user_message}"
        })
    else:
        messages.append({
            "role": "user", 
            "content": f"{user_message}\n\n(No documents uploaded yet. Please upload a PDF or TXT file first.)"
        })

    # Add recent chat history
    for msg in chat_history[-6:]:
        messages.insert(-1, msg)

    assistant_message = None
    used_fallback = False

    if client is None:
        assistant_message = local_answer(user_message, context, sources)
        used_fallback = True
    else:
        try:
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=messages,
                max_tokens=500,
                temperature=0.3
            )
            assistant_message = response.choices[0].message.content
        except AuthenticationError:
            assistant_message = (
                local_answer(user_message, context, sources)
                + "\n\n---\nNote: OpenAI API key is invalid. Using local extractive answers. "
                "Update OPENAI_API_KEY in your .env file."
            )
            used_fallback = True
        except RateLimitError:
            assistant_message = (
                local_answer(user_message, context, sources)
                + "\n\n---\nNote: OpenAI quota/credits are exhausted. Using local extractive answers. "
                "Add credits at https://platform.openai.com/settings/organization/billing/"
            )
            used_fallback = True
        except APIError as e:
            assistant_message = (
                local_answer(user_message, context, sources)
                + f"\n\n---\nNote: OpenAI API error ({e.__class__.__name__}). "
                "Using local extractive answers."
            )
            used_fallback = True
        except Exception as e:
            return jsonify({
                'error': f'Chat failed: {type(e).__name__}: {e}'
            }), 500

    # Update history
    chat_history.append({"role": "user", "content": user_message})
    chat_history.append({"role": "assistant", "content": assistant_message})

    return jsonify({
        'response': assistant_message,
        'sources': sources,
        'fallback': used_fallback
    })

@app.route('/clear', methods=['POST'])
def clear():
    global chat_history
    chat_history = []
    document_store.clear()
    return jsonify({'success': True})

if __name__ == '__main__':
    os.makedirs('uploads', exist_ok=True)
    app.run(debug=True, port=5000)
