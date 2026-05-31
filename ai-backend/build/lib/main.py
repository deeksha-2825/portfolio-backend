from fastapi import FastAPI, Request
from pydantic import BaseModel
from openai import OpenAI
import os
from dotenv import load_dotenv
from fastapi.middleware.cors import CORSMiddleware
from collections import defaultdict

# Load the secret key from the .env file
load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Read your resume context
with open("context.txt", "r") as file:
    system_context = file.read()

app = FastAPI()

# Allow Next.js frontend to talk to this backend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

class FeedbackRequest(BaseModel):
    rating: int  # e.g., 1 to 5 stars
    comments: str = ""

# --- THE RATE LIMITER ---
# This dictionary remembers IPs and how many questions they've asked
user_request_counts = defaultdict(int)
MAX_QUESTIONS = 3

@app.post("/feedback")
async def submit_feedback(request: FeedbackRequest):
    # Log the feedback or save to a database
    with open("feedback_log.txt", "a") as f:
        f.write(f"Rating: {request.rating}/5 | Comments: {request.comments}\n")
    return {"message": "Thank you for your feedback!"}

@app.post("/chat")
async def chat_with_bot(request: ChatRequest, fastapi_req: Request):
    try:
        # 1. Grab the recruiter's IP address
        client_ip = fastapi_req.client.host
        
        # 2. Check if they have hit the limit
        if user_request_counts[client_ip] >= MAX_QUESTIONS:
            return {
                "reply": "I've reached my chat limit for this session to keep cloud costs optimized! Please email Deeksha directly at deeksharamakrishna6@gmail.com to continue the conversation or arrange an interview."
            }
        
        # 3. If they are under the limit, increase their count by 1
        user_request_counts[client_ip] += 1

        # 4. Send the question to OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_context},
                {"role": "user", "content": request.message}
            ]
        )
        
        ai_reply = response.choices[0].message.content
        
        # 5. Append feedback request on the 3rd question.
        if user_request_counts[client_ip] == MAX_QUESTIONS:
            ai_reply += "\n\n*(Notice: We have reached our 3-question limit for this session to keep cloud costs optimized! Please use the feedback feature to rate this chat from 1-5 stars. If you wish to continue, please email Deeksha directly!)*"

        return {"reply": ai_reply}
        
    except Exception as e:
        return {"reply": f"Sorry, I ran into an architecture error: {str(e)}"}