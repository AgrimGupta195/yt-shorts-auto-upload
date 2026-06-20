from pathlib import Path

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from app.config import settings
from app.models import ShortScript

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class YouTubeCredentialsError(RuntimeError):
    pass


class YouTubeService:
    def __init__(self):
        self.credentials = self._load_credentials()

    def _credentials_from_env(self) -> Credentials | None:
        if not all(
            [
                settings.youtube_client_id,
                settings.youtube_client_secret,
                settings.youtube_refresh_token,
            ]
        ):
            return None
        return Credentials(
            token=None,
            refresh_token=settings.youtube_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.youtube_client_id,
            client_secret=settings.youtube_client_secret,
            scopes=SCOPES,
        )

    def _credentials_from_files(self) -> Credentials | None:
        token_path = Path(settings.youtube_token_file)
        secrets_path = Path(settings.youtube_client_secrets_file)
        creds = None

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise YouTubeCredentialsError(
                    "YouTube token refresh failed. Regenerate youtube_token.json locally with "
                    "python get_youtube_token.py or provide fresh YOUTUBE_* secrets."
                ) from exc
            token_path.write_text(creds.to_json(), encoding="utf-8")
            return creds

        if not secrets_path.exists():
            return None

        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
        creds = flow.run_local_server(port=0)
        token_path.write_text(creds.to_json(), encoding="utf-8")
        return creds

    def _load_credentials(self) -> Credentials:
        token_path = Path(settings.youtube_token_file)
        creds = self._credentials_from_files() or self._credentials_from_env()
        if not creds:
            raise YouTubeCredentialsError(
                "YouTube credentials missing. Set YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, and YOUTUBE_REFRESH_TOKEN, or provide "
                "client_secrets.json and run OAuth locally once."
            )

        if not creds.valid:
            if not creds.refresh_token:
                raise YouTubeCredentialsError("YouTube credentials are invalid and no refresh token is available.")
            try:
                creds.refresh(Request())
            except RefreshError as exc:
                raise YouTubeCredentialsError(
                    "YouTube credentials have expired or been revoked. Regenerate them locally with "
                    "python get_youtube_token.py or update the YOUTUBE_* secrets."
                ) from exc
            if token_path.parent.exists():
                token_path.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def upload_short(self, video_path: Path, script: ShortScript) -> str:
        youtube = build("youtube", "v3", credentials=self.credentials)
        tags = list(script.tags)
        if "Shorts" not in tags:
            tags.append("Shorts")

        description = script.description
        if "#Shorts" not in description:
            description = f"{description}\n\n#Shorts"

        body = {
            "snippet": {
                "title": script.title[:100],
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": "22",
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
        request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        try:
            response = None
            while response is None:
                _, response = request.next_chunk()
        except HttpError as exc:
            if "youtubeSignupRequired" in str(exc):
                raise RuntimeError(
                    "YouTube channel not activated. Open https://www.youtube.com, sign in with "
                    "the same Google account used for OAuth, create a channel, then run: "
                    "python get_youtube_token.py"
                ) from exc
            raise RuntimeError(f"YouTube upload failed: {exc}") from exc

        video_id = response["id"]
        return f"https://www.youtube.com/shorts/{video_id}"
