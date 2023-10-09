# Use the official Python image as the base image
FROM python:3.9

# Set the working directory
WORKDIR /tibet

# Create and activate a virtual environment
RUN python -m venv venv
RUN /bin/bash -c "source venv/bin/activate"

# Always needed
RUN pip install --extra-index-url https://pypi.chia.net/simple/ chia-dev-tools

# Install requirements from requirements.txt
COPY requirements.txt ./
RUN pip install -r requirements.txt

# Install requirements from api-requirements.txt
COPY api-requirements.txt ./
RUN pip install -r api-requirements.txt

# Clone rest of files files
COPY *.py ./
COPY clsp/ ./clsp/
COPY include ./include/
COPY build.sh ./

# Build code
RUN mkdir clvm
RUN chmod +x build.sh && ./build.sh

# Start the Uvicorn server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
