from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from starlette.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import time
import os
from datetime import datetime

# Configuración
TENANT_ID = os.getenv("TENANT_ID")
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
AUTH_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/authorize"
TOKEN_URL = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
REDIRECT_URI = "http://localhost:9000/auth/callback"
SCOPES = "https://graph.microsoft.com/Calendars.ReadWrite openid profile offline_access"

# Variables para almacenar tokens
access_token = None
refresh_token = None
token_expiry = 0

app = FastAPI()

origins = [
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Definimos el modelo para los datos de la reunión
class Attendee(BaseModel):
    emailAddress: str
    name: str

class MeetingData(BaseModel):
    start: datetime
    end: datetime
    attendees: list[Attendee]

@app.get("/")
def read_root():
    return {"Hello": "World"}

# Endpoint para redirigir a la página de autenticación de Microsoft
@app.get("/auth")
async def auth():
    auth_url = (
        f"{AUTH_URL}?client_id={CLIENT_ID}&response_type=code&redirect_uri={REDIRECT_URI}&scope={SCOPES}"
    )
    return RedirectResponse(auth_url)

# Callback para manejar el código de autorización
@app.get("/auth/callback")
async def auth_callback(code: str):
    global access_token, refresh_token, token_expiry
    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "scope": SCOPES,
            },
        )
        if token_response.status_code != 200:
            raise HTTPException(status_code=400, detail=token_response.text)

        token_data = token_response.json()
        access_token = token_data["access_token"]
        refresh_token = token_data["refresh_token"]
        expires_in = token_data["expires_in"]
        token_expiry = time.time() + expires_in

        return {"access_token": access_token, "expires_in": expires_in}

# Función para renovar el token de acceso
async def renew_access_token():
    global access_token, refresh_token, token_expiry
    if time.time() > token_expiry - 60:
        async with httpx.AsyncClient() as client:
            token_response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": SCOPES,
                },
            )
            if token_response.status_code != 200:
                raise HTTPException(status_code=400, detail=token_response.text)

            token_data = token_response.json()
            access_token = token_data["access_token"]
            refresh_token = token_data.get("refresh_token", refresh_token)
            expires_in = token_data["expires_in"]
            token_expiry = time.time() + expires_in

@app.post("/create_meeting")
async def create_meeting(meeting_data: MeetingData):
    await renew_access_token()

    # Crear los datos del evento con los parámetros recibidos
    event_data = {
        "subject": "Reunión de prueba",
        "body": {
            "contentType": "HTML",
            "content": "Esta es una invitación para una reunión de prueba."
        },
        "start": {
            "dateTime": meeting_data.start.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "America/Lima"
        },
        "end": {
            "dateTime": meeting_data.end.strftime("%Y-%m-%dT%H:%M:%S"),
            "timeZone": "America/Lima"
        },
        "location": {
            "displayName": "Microsoft Teams Meeting"
        },
        "attendees": [
            {
                "emailAddress": {
                    "address": attendee.emailAddress,
                    "name": attendee.name
                },
                "type": "required"
            }
            for attendee in meeting_data.attendees
        ],
        "allowNewTimeProposals": True,
        "isOnlineMeeting": True,
        "onlineMeetingProvider": "teamsForBusiness"
    }

    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://graph.microsoft.com/v1.0/me/events", json=event_data, headers=headers
        )
        if response.status_code != 201:
            raise HTTPException(status_code=response.status_code, detail=response.text)

        return response.json()
