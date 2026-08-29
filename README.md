# Voice Studio (MVP)

Voice Studio is a full-stack web application for designing custom AI voices and generating narrated audio using **Qwen3-TTS**. The project is split into a local web application and a remote GPU worker running on Google Colab (Tesla T4).

---

## What This Project Does

1. **Voice Design:** Define a voice persona using natural language descriptions (e.g., "warm, deep male voice with an empathetic tone") to generate and preview synthesized audio.
2. **Voice Cloning & Narration:** Clone generated voices and render full multi-paragraph scripts with natural delivery directions.
3. **Local & Cloud Hybrid Architecture:** The web app and database run locally on your laptop, while resource-intensive 1.7B model inference is offloaded to a free Google Colab T4 GPU instance.

---

## Application Architecture

```
[ Local Laptop ]
├── React + Vite Frontend (:5173) ──> Interacts via Local Web Server
├── FastAPI Backend (:8000) ───────> Manages Auth, Database & Job Queue
└── ngrok Tunnel (Port 8000) ──────> Secure HTTPS Gateway to Internet

[ Google Cloud Platform ]
└── Google Colab (T4 GPU Worker) ──> Polls Backend & Runs Qwen3-TTS Inference
```

---

## Software & Prerequisites Required

Before running the application, make sure the following applications and tools are installed:

1. **Python 3.11+** (for running the backend locally)
2. **Node.js 20+ & npm** (for running the React/Vite frontend)
3. **ngrok CLI** (to expose port 8000 to Google Colab)
4. **Google Account** (to access Google Colab T4 GPU instances)

---

## Local Execution Commands

Open separate terminal windows on your local machine to launch each service:

### Terminal 1: Backend Server (FastAPI)
```powershell
# Run these commands manually
# Navigate to the backend directory
cd backend

# Install dependencies (first time only)
pip install -r requirements.txt

# Set local execution environment variables
$env:WORKER_TOKEN="dev-worker-token"
$env:DEV_LOGIN="1"
$env:DEFAULT_JOB_BACKEND="qwen"
$env:FRONTEND_URL="http://localhost:5173"

# Start the local FastAPI server on Port 8000
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Terminal 2: Frontend Client (React / Vite)

```powershell
# Navigate to the frontend directory
cd frontend

# Install packages (first time only)
npm install

# Start the Vite development web server
npm run dev
```

### Terminal 3: Secure Tunnel (ngrok)

```powershell
# Expose port 8000 to the public internet
ngrok http 8000
```

---

## Remote Worker Setup (Google Colab T4 GPU)

Because local integrated GPUs (such as Intel Iris Xe) cannot run the 1.7B parameter PyTorch model, inference is executed via Google Colab.

1. Open Google Colab and load `colab_worker.ipynb` from your repository.
2. Navigate to **Runtime > Change runtime type** and select **T4 GPU**.
3. Set your active ngrok URL and shared secret token in the Colab cell:

```python
%cd /content/Qwen3TTS-Studio/worker
import os
os.environ["BACKEND_URL"] = "https://your-ngrok-static-domain.ngrok-free.dev"
os.environ["WORKER_TOKEN"] = "dev-worker-token"
os.environ["WORKER_BACKEND"] = "qwen"

!python -m qwen_tts_worker.main --backend qwen
```

4. Click **Runtime > Run All**.

---

## Testing & Verification

1. Open `http://localhost:5173` in your browser.
2. Click **Sign in as demo (dev)**.
3. Submit a new voice prompt in the voice library.
4. Verify on the UI card that the worker status reads: **"Worker: Qwen3-TTS (real model)"**. The Colab cell log will display inference progress and return real speech back to your browser.
