#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# download_pdfs.sh — run this on your LOCAL machine
# Downloads PDFs from the remote server interactively.
#
# Usage:
#   chmod +x download_pdfs.sh
#   ./download_pdfs.sh
# ─────────────────────────────────────────────────────────────

# ── Configure these ──────────────────────────────────────────
SERVER="ubuntu@YOUR_SERVER_IP"          # e.g. ubuntu@12.34.56.78
REMOTE_DIR="/home/ubuntu/youtube-project/uploaded_videos"
LOCAL_DIR="$HOME/Downloads/youtube-pdfs"
# ─────────────────────────────────────────────────────────────

mkdir -p "$LOCAL_DIR"

echo "Fetching PDF list from $SERVER..."
mapfile -t PDFS < <(ssh "$SERVER" "find $REMOTE_DIR -name '*.pdf' | sort")

if [[ ${#PDFS[@]} -eq 0 ]]; then
  echo "No PDFs found on the server."
  exit 1
fi

echo ""
echo "Available PDFs:"
for i in "${!PDFS[@]}"; do
  printf "  [%2d] %s\n" "$((i+1))" "${PDFS[$i]##*/uploaded_videos/}"
done

echo ""
echo "Enter the numbers of the PDFs to download (space-separated), or 'all' for all:"
read -r SELECTION

if [[ "$SELECTION" == "all" ]]; then
  SELECTED=("${PDFS[@]}")
else
  SELECTED=()
  for n in $SELECTION; do
    idx=$((n - 1))
    if [[ $idx -ge 0 && $idx -lt ${#PDFS[@]} ]]; then
      SELECTED+=("${PDFS[$idx]}")
    else
      echo "Warning: '$n' is not a valid number, skipping."
    fi
  done
fi

if [[ ${#SELECTED[@]} -eq 0 ]]; then
  echo "Nothing selected. Exiting."
  exit 0
fi

echo ""
echo "Downloading ${#SELECTED[@]} file(s) to $LOCAL_DIR ..."
for REMOTE_PATH in "${SELECTED[@]}"; do
  FILENAME="${REMOTE_PATH##*/}"
  echo "  -> $FILENAME"
  scp "$SERVER:$REMOTE_PATH" "$LOCAL_DIR/$FILENAME"
done

echo ""
echo "Done. Files saved to: $LOCAL_DIR"
