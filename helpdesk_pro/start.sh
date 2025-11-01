docker run --rm -p 5000:5000 \
  --env-file .env \
  -v "$(pwd)/logs:/app/logs" \
  -v "$(pwd)/instance:/app/instance" \
  helpdesk-pro:latest
