import json
import mimetypes
import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveService:
    def __init__(
        self,
        credentials_path: str,
        folder_id: str,
        credentials_json: str = "",
    ) -> None:
        self.folder_id = folder_id
        if credentials_json:
            info = json.loads(credentials_json)
            creds = Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
        else:
            creds = Credentials.from_service_account_file(
                credentials_path, scopes=DRIVE_SCOPES
            )
        self.service = build("drive", "v3", credentials=creds)

    def upload_file(self, local_path: str, filename: str | None = None) -> str:
        """Upload a PDF or image to Google Drive and return its shareable webViewLink."""
        name = filename or os.path.basename(local_path)
        mime_type, _ = mimetypes.guess_type(local_path)
        mime_type = mime_type or "application/octet-stream"

        metadata: dict = {"name": name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        uploaded = (
            self.service.files()
            .create(body=metadata, media_body=media, fields="id, webViewLink")
            .execute()
        )
        file_id = uploaded["id"]

        # Make link readable by anyone with the link
        self.service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
        ).execute()

        return uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
