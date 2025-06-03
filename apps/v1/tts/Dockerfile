FROM continuumio/miniconda3

# Create working directory
WORKDIR /app

# Copy environment file and build env
COPY environment.yml .
COPY . .

# Create conda environment
RUN conda env create -f environment.yml

# Activate environment
ENV PATH /opt/conda/envs/tts_processor_env/bin:$PATH
SHELL ["conda", "run", "-n", "tts_processor_env", "/bin/bash", "-c"]

# Expose the Flask port
EXPOSE 5000

# Run the app
CMD ["/bin/bash", "-c", "source activate tts_processor_env && python api_service.py"]
