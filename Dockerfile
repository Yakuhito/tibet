# Use the official Python image as the base image
FROM python:3.9

# Set the working directory
WORKDIR /tibet

# Install Git
RUN apt-get update && \
    apt-get install -y git supervisor

# Set up the Go environment
ENV GOPATH /go
ENV PATH $PATH:/usr/local/go/bin:$GOPATH/bin

# Cache-busting argument
ARG VERSION

# Clone the repository
RUN git clone https://github.com/Yakuhito/tibet.git .

# Create and activate a virtual environment
WORKDIR /tibet
RUN python -m venv venv
RUN /bin/bash -c "source venv/bin/activate"

# Install requirements from requirements.txt
RUN pip install -r requirements.txt

# Install requirements from api-requirements.txt
RUN pip install -r api-requirements.txt

# Run your additional pip install commands here
RUN pip install --extra-index-url https://pypi.chia.net/simple/ chia-internal-custody
RUN pip install --extra-index-url https://pypi.chia.net/simple/ chia-dev-tools

# Start the Uvicorn server
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000"]

