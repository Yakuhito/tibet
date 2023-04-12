# Use the official Python image as the base image
FROM python:3.9

# Set the working directory
WORKDIR /tibet

# Install Git
RUN apt-get update && \
    apt-get install -y git supervisor

# Install Go 1.16
RUN wget -q https://golang.org/dl/go1.16.10.linux-amd64.tar.gz -O go1.16.tar.gz && \
    tar -C /usr/local -xzf go1.16.tar.gz && \
    rm go1.16.tar.gz

# Set up the Go environment
ENV GOPATH /go
ENV PATH $PATH:/usr/local/go/bin:$GOPATH/bin

# Clone the repository
RUN git clone https://github.com/Yakuhito/tibet.git .

# Compile and run the Go application
WORKDIR /tibet/fml
RUN go build -o fml main.go
RUN chmod +x fml

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

# Run server & fml (supervisord)
RUN mv supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Start supervisord to manage both the Go application and the Uvicorn server
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]

