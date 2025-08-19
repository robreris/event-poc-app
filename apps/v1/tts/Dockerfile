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

## Sam 
RUN wget -O /models/en_US-sam-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/sam/medium/en_US-sam-medium.onnx && \
    wget -O /models/en_US-sam-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/sam/medium/en_US-sam-medium.onnx.json
## hfc_male
RUN wget -O /models/en_US-hfc_male-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx && \
    wget -O /models/en_US-hfc_male-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_male/medium/en_US-hfc_male-medium.onnx.json
## hfc_female
RUN wget -O /models/en_US-hfc_female-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx && \
    wget -O /models/en_US-hfc_female-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/hfc_female/medium/en_US-hfc_female-medium.onnx.json
# John 
RUN wget -O /models/en_US-john-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/john/medium/en_US-john-medium.onnx && \
    wget -O /models/en_US-john-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/john/medium/en_US-john-medium.onnx.json
# Norman 
RUN wget -O /models/en_US-norman-medium.onnx https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx && \
    wget -O /models/en_US-norman-medium.onnx.json https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/norman/medium/en_US-norman-medium.onnx.json

# Activate environment
ENV PATH /opt/conda/envs/tts_processor_env/bin:$PATH
SHELL ["conda", "run", "-n", "tts_processor_env", "/bin/bash", "-c"]

# Expose the Flask port
EXPOSE 5000

# Run the app
CMD ["/bin/bash", "-c", "source activate tts_processor_env && python api_service.py"]
