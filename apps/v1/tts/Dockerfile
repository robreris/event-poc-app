FROM continuumio/miniconda3

# Create working directory
WORKDIR /app

# Copy environment file and build env
COPY environment.yml .
COPY . .

# Create conda environment
RUN conda env create -f environment.yml
RUN conda run -n tts_processor_env python -m pip install --upgrade pip

# Download Piper binary
RUN mkdir -p /root/.local/share/ && wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz && \
    tar -xvf piper_amd64.tar.gz && \
    mv piper /root/.local/share/

ENV PATH /root/.local/share/piper:$PATH

# Download Piper models
RUN mkdir -p /models

## Ryan
RUN wget -O /models/en_US-ryan-high.onnx https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/high/en_US-ryan-high.onnx && \
    wget -O /models/en_US-ryan-high.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/ryan/high/en_US-ryan-high.onnx.json
## Joe
RUN wget -O /models/en_US-joe-medium.onnx  https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/joe/medium/en_US-joe-medium.onnx && \
    wget -O /models/en_US-joe-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/joe/medium/en_US-joe-medium.onnx.json
## Kathleen 
RUN wget -O /models/en_US-kathleen-low.onnx  https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/kathleen/low/en_US-kathleen-low.onnx && \
    wget -O /models/en_US-kathleen-low.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/kathleen/low/en_US-kathleen-low.onnx.json
## Amy 
RUN wget -O /models/en_US-amy-medium.onnx  https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx && \
    wget -O /models/en_US-amy-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/amy/medium/en_US-amy-medium.onnx.json

# Activate environment
ENV PATH /opt/conda/envs/tts_processor_env/bin:$PATH
SHELL ["conda", "run", "-n", "tts_processor_env", "/bin/bash", "-c"]

# Expose the Flask port
EXPOSE 5000

# Run the app
CMD ["/bin/bash", "-c", "source activate tts_processor_env && python api_service.py"]
