# main.py
import json
from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import numpy as np
import faiss
import os
import requests
from openai import OpenAI
import logging
from fastapi import Body
from fastapi.responses import JSONResponse

app = FastAPI()

# Enable CORS for all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load marks data from q-vercel-python.json
with open("q-vercel-python.json", "r") as f:
    marks_list = json.load(f)
marks_data = {item["name"]: item["marks"] for item in marks_list}

# Load FAISS index, embeddings, and metadata
index = faiss.read_index("faiss_index.bin")
embeddings = np.load("embeddings.npy")
with open("metadatas.json", "r", encoding="utf-8") as f:
    metadatas = json.load(f)
rag_data_path = os.path.join('webscraper', 'rag_dataset.jsonl')
rag_records = []
with open(rag_data_path, 'r', encoding='utf-8') as f:
    for line in f:
        try:
            rag_records.append(json.loads(line))
        except Exception:
            pass

token = os.getenv('OPENAI_API_KEY', "")
openai_client = OpenAI(api_key=token, base_url="https://aipipe.org/openai/v1")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def retrieve_similar(query_embedding, metadatas, top_k=3):
    query_embedding = np.array(query_embedding, dtype=np.float32).reshape(1, -1)
    D, I = index.search(query_embedding, top_k)
    results = []
    for idx, dist in zip(I[0], D[0]):
        if idx < len(metadatas):
            results.append({
                'score': float(-dist),
                'index': int(idx),
                'metadata': metadatas[idx]
            })
    return results

class QARequest(BaseModel):
    question: str
    image: str = None



@app.api_route("/api/", methods=["POST", "GET"])
@app.api_route("/", methods=["POST", "GET"])
async def answer_question(request: QARequest = Body(None), question: str = Query(None), image: str = Query(None)):
    # Support both POST (with JSON body) and GET (with query params)
    if request is not None:
        query = request.question
        img = request.image
    else:
        query = question
        img = image

    logger.info(f"Received question: {query}")
    if img:
        logger.info("Image provided with the request.")
    else:
        logger.info("No image provided.")

    # Step 1: Get embedding for the question
    try:
        query_embedding = openai_client.embeddings.create(
            input=query,
            model="text-embedding-ada-002"
        ).data[0].embedding
        logger.info("Query embedding generated successfully.")
    except Exception as e:
        logger.error(f"Error generating embedding: {e}")
        return {"answer": f"Embedding error: {e}", "links": []}
    # Step 2: Retrieve similar contexts
    try:
        faiss_results = retrieve_similar(query_embedding, metadatas, top_k=3)
        logger.info(f"Retrieved {len(faiss_results)} similar contexts from FAISS.")
    except Exception as e:
        logger.error(f"Error retrieving similar contexts: {e}")
        return {"answer": f"FAISS error: {e}", "links": []}
    faiss_context = "\n---\n".join([
        rag_records[result['index']]['text'] for result in faiss_results
    ])
    # Step 3: Compose prompt
    grounded_prompt = (
        f"You are a helpful assistant for the IITM TDS course. "
        f"Use the following context to answer the user's question.\n\n"
        f"Context:\n{faiss_context}\n\nQuestion: {query}\nAnswer:"
    )
    # Step 4: Prepare OpenAI API call
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    messages = [
        {"role": "system", "content": "You are a helpful assistant for the IITM TDS course."},
        {"role": "user", "content": grounded_prompt}
    ]
    if img:
        messages[-1]["content"] = [
            {"type": "text", "text": grounded_prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/webp;base64,{img}"}}
        ]
    data = {
        "model": "gpt-4o-mini",
        "messages": messages,
        "max_tokens": 256,
        "temperature": 0.2
    }
    logger.info("Sending request to OpenAI API...")
    response = requests.post(
        "https://aipipe.org/openai/v1/chat/completions",
        headers=headers,
        json=data
    )
    if response.status_code == 200:
        answer = response.json()['choices'][0]['message']['content']
        logger.info("Received answer from OpenAI API.")
    else:
        answer = f"Error: {response.status_code} {response.text}"
        logger.error(f"OpenAI API error: {response.status_code} {response.text}")
    # Step 5: Find links from the retrieved context
    links = []
    for result in faiss_results:
        idx = result['index']
        url = rag_records[idx].get('url')
        text = rag_records[idx].get('text', '')
        if url:
            link_text = text.split(". ")[0][:100]
            links.append({"url": url, "text": link_text})
    logger.info(f"Returning {len(links)} links with the answer.")
    # Add CORS headers to the response
    response_data = {"answer": answer, "links": links}
    return JSONResponse(content=response_data, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "*"
    })