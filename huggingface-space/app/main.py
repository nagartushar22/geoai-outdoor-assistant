from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse

from app import config
from app.llm import ModelUnavailable, local_model
from app.recommendation import make_recommendation
from app.schemas import RecommendationRequest, RecommendationResponse


app = FastAPI(
    title="GeoAI Outdoor Assistant",
    description="A small local language model plus live map, weather, and air-quality data.",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse)
async def home():
    return HTMLResponse(
        """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>GeoAI Outdoor Assistant</title><style>
body{font:16px system-ui,sans-serif;background:#f4f7f5;color:#18231d;margin:0;padding:32px}
main{max-width:820px;margin:auto;background:white;border-radius:18px;padding:28px;box-shadow:0 8px 30px #19332212}
h1{margin-top:0;color:#155b43}textarea{width:100%;min-height:105px;padding:12px;border:1px solid #bdccc2;border-radius:10px;font:inherit;box-sizing:border-box}
button{margin-top:12px;background:#176b4f;color:#fff;border:0;border-radius:9px;padding:11px 18px;font:inherit;cursor:pointer}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f4f7f5;border-radius:10px;padding:16px;min-height:45px}
small{color:#5b6a61}.sources{margin-top:22px;font-size:13px;color:#5b6a61}
</style></head><body><main><h1>GeoAI Outdoor Assistant</h1>
<p>Ask where and when to go outdoors. The app compares mapped places with forecast weather and air quality.</p>
<textarea id="question">Where can I go running tomorrow evening near Powai?</textarea><br>
<label for="api-key"><small>API key (only if your server requires one)</small></label><br>
<input id="api-key" type="password" autocomplete="off" placeholder="Optional X-API-Key" style="width:100%;box-sizing:border-box;padding:10px;border:1px solid #bdccc2;border-radius:9px;margin-top:5px">
<button id="send">Find a place and time</button><p id="status"></p><pre id="result">Your recommendation will appear here.</pre>
<div class="sources">Map data: © OpenStreetMap contributors. <a href="https://operations.osmfoundation.org/policies/nominatim/" target="_blank" rel="noreferrer">Nominatim usage policy</a>. Forecasts from <a href="https://open-meteo.com/" target="_blank" rel="noreferrer">Open-Meteo</a>. Scores are heuristic guidance, not a safety guarantee.</div></main>
<script>const button=document.querySelector('#send');button.onclick=async()=>{const q=document.querySelector('#question').value;const status=document.querySelector('#status');const result=document.querySelector('#result');const headers={'Content-Type':'application/json'};const key=document.querySelector('#api-key').value;if(key)headers['X-API-Key']=key;button.disabled=true;status.textContent='Checking live sources…';result.textContent='';try{const r=await fetch('/recommend',{method:'POST',headers:headers,body:JSON.stringify({question:q})});const d=await r.json();status.textContent=d.status==='ok'?'Recommendation ready.':d.status==='clarification'?'I need one more detail.':d.status==='error'?'No recommendation available.':'Request failed ('+r.status+').';result.textContent=JSON.stringify(d,null,2)}catch(e){status.textContent='Request failed.';result.textContent=String(e)}finally{button.disabled=false}};</script>
</body></html>"""
    )


@app.get("/health")
async def health():
    return {"status": "ok", "model_ready": await local_model.is_ready()}


@app.post("/recommend", response_model=RecommendationResponse)
async def recommend(payload: RecommendationRequest, x_api_key: str | None = Header(default=None)):
    if config.API_KEY and x_api_key != config.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
    try:
        return await make_recommendation(payload.question, payload.radius_km)
    except ModelUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

