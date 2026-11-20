FROM python:3.14-slim

WORKDIR /app

# Install dependencies
RUN pip install flask requests

# Copy the hunter application
COPY . .

# Environment for unique port configuration
ENV HUNTER_PORT=3245
ENV BINANCE_API_KEY=""
ENV BINANCE_API_SECRET=""

# Expose the hunter dashboard port
EXPOSE 3245

# Command: run the Binance Hunter
CMD ["python", "app.py"]
