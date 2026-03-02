#!/bin/bash
# ─────────────────────────────────────────────────────────────
# upload.sh  –  Upload videos and transcripts to the server
#
# Run from your local machine. Opens a file picker dialog.
# You can also still pass files as CLI args:
#   ./upload.sh lecture.mp4 transcript.pkl
#
# Set SERVER below to your server's SSH alias or user@host.
# ─────────────────────────────────────────────────────────────

SERVER="ubuntu@YOUR_SERVER_IP_OR_HOSTNAME"
REMOTE_DIR="/home/ubuntu/youtube-project/uploads"

# ── File picker ──────────────────────────────────────────────
pick_files() {
    case "$(uname)" in
        Darwin)
            # macOS native picker (supports multi-select)
            osascript <<'EOF'
set chosen to choose file with prompt "Select video or transcript files to upload:" ¬
    of type {"public.movie", "public.mpeg-4", "org.python.pickled-data", "public.data"} ¬
    with multiple selections allowed
set paths to {}
repeat with f in chosen
    set end of paths to POSIX path of f
end repeat
set AppleScript's text item delimiters to linefeed
return paths as text
EOF
            ;;
        Linux)
            if command -v zenity &>/dev/null; then
                zenity --file-selection \
                    --title="Select files to upload" \
                    --file-filter="Videos and transcripts | *.mp4 *.mkv *.mov *.avi *.webm *.pkl" \
                    --multiple --separator=$'\n'
            elif command -v kdialog &>/dev/null; then
                kdialog --getopenfilename . "*.mp4 *.mkv *.mov *.avi *.webm *.pkl" \
                    --title "Select files to upload" --multiple
            else
                echo "ERROR: No GUI file picker found. Install zenity (sudo apt install zenity) or pass files as arguments." >&2
                return 1
            fi
            ;;
        *)
            echo "ERROR: Unsupported OS for GUI picker. Pass files as CLI arguments instead." >&2
            return 1
            ;;
    esac
}

# ── Collect files (CLI args or picker) ───────────────────────
if [ $# -gt 0 ]; then
    files=("$@")
else
    raw=$(pick_files) || exit 1
    if [ -z "$raw" ]; then
        echo "No files selected."
        exit 0
    fi
    # Split newline-separated paths into array
    mapfile -t files <<< "$raw"
fi

# ── Upload each file ─────────────────────────────────────────
for file in "${files[@]}"; do
    [ -z "$file" ] && continue

    if [ ! -f "$file" ]; then
        echo "ERROR: File not found: $file"
        continue
    fi

    ext="${file##*.}"
    case "$ext" in
        mp4|mkv|mov|avi|webm|pkl)
            echo "Uploading: $(basename "$file") → $SERVER:$REMOTE_DIR/"
            rsync -ah --progress "$file" "$SERVER:$REMOTE_DIR/"
            if [ $? -eq 0 ]; then
                echo "✓ Done: $(basename "$file")"
            else
                echo "✗ Failed: $(basename "$file")"
            fi
            ;;
        *)
            echo "Skipping unsupported file type: $(basename "$file") (.$ext)"
            ;;
    esac
done
