FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY devin_kpi ./devin_kpi
COPY scripts ./scripts
COPY .streamlit ./.streamlit
COPY docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh

RUN pip install --no-cache-dir .

RUN useradd -m appuser && mkdir -p /app/data && chown -R appuser /app
USER appuser

EXPOSE 8501

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["streamlit", "run", "devin_kpi/app/Home.py", "--server.address", "0.0.0.0", "--server.headless", "true"]
