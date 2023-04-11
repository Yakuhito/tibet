# Use the official Python image as the base image
FROM python:3.9

# Set the working directory
WORKDIR /tibet

# Install Git
RUN apt-get update && \
    apt-get install -y git

# Clone the repository
RUN git clone https://github.com/Yakuhito/tibet.git .

# Install Go
RUN apt-get install -y golang-go

# Compile and run the Go application
WORKDIR /tibet/fml
RUN go build -o main main.go
RUN chmod +x main
CMD ["./main"]

# Create and activate a virtual environment
WORKDIR /tibet
RUN python -m venv venv
RUN /bin/bash -c "source venv/bin/activate"

# Install requirements from requirements.txt
COPY requirements.txt .
RUN pip install -r requirements.txt

# Run your additional pip install commands here
RUN pip install --extra-index-url https://pypi.chia.net/simple/ chia-internal-custody
RUN pip install --extra-index-url https://pypi.chia.net/simple/ chia-dev-tools

# Install and run the Uvicorn server
RUN pip install uvicorn
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]
