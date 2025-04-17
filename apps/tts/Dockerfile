FROM continuumio/miniconda3

# Create working directory
WORKDIR /app

# Copy environment file and build env
COPY environment.yml .
COPY app .

# Create conda environment
RUN conda env create -f environment.yml

# Activate environment
ENV PATH /opt/conda/envs/azure_speech_env/bin:$PATH
SHELL ["conda", "run", "-n", "azure_speech_env", "/bin/bash", "-c"]

# Expose the Flask port
EXPOSE 5000

# Run the app
CMD ["/bin/bash", "-c", "source activate azure_speech_env && python api_service.py"]
