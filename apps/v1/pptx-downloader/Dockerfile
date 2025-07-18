# Base image with Miniconda
FROM continuumio/miniconda3

# Set work directory
WORKDIR /app

# Copy environment and app files
COPY environment.yml .
#COPY app .
COPY tasks.py .

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libreoffice \
    poppler-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create conda environment
RUN conda env create -f environment.yml

# Activate environment and set as default
ENV PATH /opt/conda/envs/pptx_downloader_env/bin:$PATH
SHELL ["conda", "run", "-n", "pptx_downloader_env", "/bin/bash", "-c"]

# Expose Flask port
EXPOSE 5000

# Run the Flask app
CMD ["/bin/bash", "-c", "source activate pptx_downloader_env && python api_service.py"]
