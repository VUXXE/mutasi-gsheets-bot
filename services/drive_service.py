import json
import mimetypes
import os
import time
import boto3
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


class DriveService:
    """
    File storage service:
    - Uses InstaCloud S3 Storage if BUCKET_NAME + AWS_ENDPOINT_URL_S3 are set.
    - Falls back to Google Drive (Shared Drive) otherwise.
    """

    def __init__(
        self,
        credentials_path: str,
        folder_id: str,
        credentials_json: str = "",
    ) -> None:
        self.folder_id = folder_id
        self.bucket = os.getenv("BUCKET_NAME", "")
        self.s3_endpoint = os.getenv("AWS_ENDPOINT_URL_S3", "")
        self.s3_region = os.getenv("AWS_REGION", "auto")

        if self.bucket and self.s3_endpoint:
            self.s3 = boto3.client(
                "s3",
                endpoint_url=self.s3_endpoint,
                region_name=self.s3_region,
            )
            self.service = None
        else:
            self.s3 = None
            if credentials_json:
                info = json.loads(credentials_json)
                creds = Credentials.from_service_account_info(info, scopes=DRIVE_SCOPES)
            else:
                creds = Credentials.from_service_account_file(
                    credentials_path, scopes=DRIVE_SCOPES
                )
            self.service = build("drive", "v3", credentials=creds)

    def upload_file(self, local_path: str, filename: str | None = None) -> str:
        """Upload a PDF or image and return a shareable URL."""
        name = filename or os.path.basename(local_path)
        mime_type, _ = mimetypes.guess_type(local_path)
        mime_type = mime_type or "application/octet-stream"

        if self.s3 is not None:
            key = f"uploads/{int(time.time())}_{name}"
            with open(local_path, "rb") as f:
                self.s3.put_object(
                    Bucket=self.bucket,
                    Key=key,
                    Body=f,
                    ContentType=mime_type,
                )
            host = self.s3_endpoint.replace("https://", "").replace("http://", "").rstrip("/")
            return f"https://{self.bucket}.{host}/{key}"

        metadata: dict = {"name": name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

        media = MediaFileUpload(local_path, mimetype=mime_type, resumable=True)
        uploaded = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        file_id = uploaded["id"]

        self.service.permissions().create(
            fileId=file_id,
            body={"type": "anyone", "role": "reader"},
            supportsAllDrives=True,
        ).execute()

        return uploaded.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
