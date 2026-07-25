#!/usr/bin/env bash
set -euo pipefail

RSSHUB_CONTAINER="${INTELISCOPE_RSSHUB_CONTAINER:-inteliscope-rsshub}"
DATA_DIR="${INTELISCOPE_DATA_DIR:-/opt/inteliscope/data}"
SERVICE_IMAGE="${INTELISCOPE_IMAGE:?INTELISCOPE_IMAGE must name a locally loaded Inteliscope image}"

[[ "$DATA_DIR" = /* ]] || {
  echo "INTELISCOPE_DATA_DIR must be an absolute path" >&2
  exit 1
}
[[ -d "$DATA_DIR" ]] || {
  echo "Inteliscope data directory not found: $DATA_DIR" >&2
  exit 1
}
docker inspect "$RSSHUB_CONTAINER" >/dev/null
docker image inspect "$SERVICE_IMAGE" >/dev/null

if [[ -f "$DATA_DIR/secrets.env" ]]; then
  backup_dir="$DATA_DIR/backups"
  backup="$backup_dir/secrets-pre-rsshub-bilibili-$(date -u +%Y%m%dT%H%M%SZ).env"
  install -d -m 700 "$backup_dir"
  install -m 600 "$DATA_DIR/secrets.env" "$backup"
  echo "SecretStore backup: $backup"
fi

# A fresh browser context contains no account profile or login state. It visits
# one public page and emits only its anonymous Bilibili anti-bot cookies into
# the downstream SecretStore writer; the values are never printed.
timeout --signal=KILL 40s \
  docker exec "$RSSHUB_CONTAINER" node --input-type=module -e '
import { chromium } from "patchright";

const executablePath = process.env.CHROMIUM_EXECUTABLE_PATH;
const userAgent = "RSSHub/1.0 (+http://github.com/DIYgod/RSSHub; like FeedFetcher-Google)";
const required = ["_uuid", "b_lsid", "b_nut", "buvid3", "buvid4", "buvid_fp"];
let browser;
try {
  browser = await chromium.launch({
    headless: true,
    executablePath,
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });
  const context = await browser.newContext({ userAgent });
  const page = await context.newPage();
  const response = await page.goto("https://space.bilibili.com/1/dynamic", {
    waitUntil: "domcontentloaded",
    timeout: 15000,
  });
  if (!response || response.status() !== 200) {
    throw new Error("unexpected Bilibili response");
  }
  await page.waitForTimeout(5000);
  const values = new Map((await context.cookies()).map((cookie) => [
    cookie.name,
    cookie.value,
  ]));
  if (required.some((name) => !values.get(name))) {
    throw new Error("anonymous Bilibili cookie set is incomplete");
  }
  process.stdout.write(
    required.map((name) => `${name}=${values.get(name)}`).join("; ")
  );
} finally {
  if (browser) {
    await browser.close().catch(() => {});
  }
}
' |
  docker run --rm -i \
    -v "$DATA_DIR:/app/data" \
    --entrypoint /app/.venv/bin/python \
    "$SERVICE_IMAGE" \
    -c '
import sys

from src.services.secret_store import SecretStore

value = sys.stdin.read()
required = ("_uuid=", "b_lsid=", "b_nut=", "buvid3=", "buvid4=", "buvid_fp=")
if not all(part in value for part in required):
    raise SystemExit("anonymous Bilibili cookie set is incomplete")
SecretStore("/app/data").set("RSSHUB_BILIBILI_ANONYMOUS_COOKIE", value)
'

echo "RSSHub anonymous Bilibili cookie refreshed; recreate the RSSHub container."
