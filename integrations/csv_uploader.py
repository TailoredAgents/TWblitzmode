import os
import time
import json
import base64
import hmac
import hashlib
import uuid
from typing import Optional

try:
    import boto3  # type: ignore
    from botocore.exceptions import BotoCoreError, ClientError  # type: ignore
except Exception:  # boto3 is optional
    boto3 = None  # type: ignore
    BotoCoreError = ClientError = Exception  # type: ignore

import requests


def _sign(data_b64: str, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), data_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def build_app_csv_url(base_url: str, csv_content: str, secret: Optional[str] = None) -> str:
    """
    Build a signed URL to our CSV endpoint served by the app.
    Requires that base_url is publicly reachable over HTTPS.
    """
    secret = secret or os.getenv("SECRET_KEY", "dev-secret")
    b64 = base64.b64encode(csv_content.encode("utf-8")).decode("ascii")
    sig = _sign(b64, secret)
    base = base_url.rstrip('/')
    if base.startswith('http://'):
        # Force https for PhantomBuster requirements
        try:
            from urllib.parse import urlparse
            pu = urlparse(base)
            if pu.netloc:
                base = f"https://{pu.netloc}"
        except Exception:
            base = base.replace('http://', 'https://', 1)
    return f"{base}/api/integrations/phantombuster/csv?data={b64}&sig={sig}"


def upload_csv_to_s3(csv_content: str) -> str:
    """
    Upload CSV content to S3 with public read access.
    Requires boto3 and environment variables:
    - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or instance role)
    - AWS_S3_BUCKET_NAME (bucket must allow public-read ACL or policy)
    - AWS_REGION (optional; defaults to us-east-1)

    Returns a public HTTPS URL to the uploaded object.
    """
    if boto3 is None:
        raise RuntimeError("boto3 not installed; cannot upload to S3")

    bucket = os.getenv("AWS_S3_BUCKET_NAME")
    if not bucket:
        raise RuntimeError("AWS_S3_BUCKET_NAME not set")
    region = os.getenv("AWS_REGION", "us-east-1")
    prefix = os.getenv("AWS_S3_PUBLIC_PREFIX", "phantombuster/csv/").rstrip('/') + '/'

    key = f"{prefix}{int(time.time())}-{uuid.uuid4().hex}.csv"

    try:
        s3 = boto3.client("s3", region_name=region)
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=csv_content.encode("utf-8"),
            ContentType="text/csv",
            ACL="public-read",
            CacheControl="max-age=300",
        )
        # Construct virtual-hosted-style URL
        if region == "us-east-1":
            return f"https://{bucket}.s3.amazonaws.com/{key}"
        return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"
    except (BotoCoreError, ClientError) as e:
        raise RuntimeError(f"S3 upload failed: {e}")


def upload_csv_to_gist(csv_content: str, filename: str = "profiles.csv") -> str:
    """
    Create a private GitHub Gist with the CSV and return the raw_url.
    Requires GITHUB_TOKEN or GH_TOKEN in environment.
    """
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
    }
    data = {
        "description": "PhantomBuster CSV input",
        "public": True,  # must be public for PB to fetch without auth
        "files": {
            filename: {
                "content": csv_content
            }
        }
    }
    resp = requests.post("https://api.github.com/gists", headers=headers, data=json.dumps(data), timeout=30)
    resp.raise_for_status()
    j = resp.json()
    files = j.get("files") or {}
    file_info = files.get(filename) or next(iter(files.values()), {})
    raw_url = file_info.get("raw_url")
    if not raw_url:
        raise RuntimeError("Could not determine gist raw_url")
    return raw_url

