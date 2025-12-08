# Use a stable Python image
FROM python:3.11-slim

# Prevent Python from buffering stdout/stderr
ENV PYTHONUNBUFFERED=1

# Set workdir in the container
WORKDIR /app

# Install system dependencies (needed for bcrypt / passlib sometimes)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the code into the image
COPY . .

# Expose the port your app will listen on
EXPOSE 8000

# Start FastAPI with uvicorn
# Note: App.app -> package.module ; "app" is the FastAPI instance inside App/app.py
CMD ["uvicorn", "App.app:app", "--host", "0.0.0.0", "--port", "8000"]
