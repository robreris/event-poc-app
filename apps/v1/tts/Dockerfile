FROM continuumio/miniconda3

# Create working directory
WORKDIR /app

# Copy environment file and build env
COPY environment.yml .
COPY . .

# Create conda environment
RUN conda env create -f environment.yml

# Download Piper binary and model
RUN conda run -n tts_processor_env python -m pip install --upgrade pip

RUN mkdir -p /root/.local/share/piper-tts/bin/ && wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz && \ 
    tar -xvf piper_amd64.tar.gz && \
    mv piper/piper /root/.local/share/piper-tts/bin/ 

RUN mkdir -p /models
RUN wget -O /models/en_GB-alan-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx && \
    wget -O /models/en_GB-alan-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_GB/alan/medium/en_GB-alan-medium.onnx.json

# Activate environment
ENV PATH /opt/conda/envs/tts_processor_env/bin:$PATH
SHELL ["conda", "run", "-n", "tts_processor_env", "/bin/bash", "-c"]

# Expose the Flask port
EXPOSE 5000

# Run the app
CMD ["/bin/bash", "-c", "source activate tts_processor_env && python api_service.py"]
