#!/bin/bash

arg="$1"

if [ -f "$arg" ]; then
    echo "Casting $arg"
    uv run caster "$arg"
elif [[ $arg =~ ^https?://(www\.)?(youtube\.com/watch\?([^#]*&)?v=|youtu\.be/)([a-zA-Z0-9_-]{11}) ]]; then
    video_id="${BASH_REMATCH[4]}"
    echo "YouTube video ID: $video_id"
    video="./videos/$video_id.webm"
    if [ ! -f "$video" ]; then
        if [ ! -x tools/yt-dlp ]; then
            echo "Downloading yt-dlp..."
            mkdir -p tools
            curl -L -o tools/yt-dlp https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp_linux
            chmod +x tools/yt-dlp
        else
            echo "yt-dlp is already installed, updating..."
            tools/yt-dlp -U
        fi
        echo "Downloading $video"
        mkdir -p ./videos
        ./tools/yt-dlp \
            -f "bestvideo[vcodec^=vp9][height<=2160]+bestaudio[acodec=opus]/best[height<=2160]" \
            --merge-output-format webm \
            -o "$video" "$arg"
    fi
    if [ -f "$video" ]; then
        echo "Casting $video"
        uv run caster "$video"
    fi
else
    echo "Error: $arg is not a valid youtube URL or file"
fi
