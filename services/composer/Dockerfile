# Pinned by digest, not by tag. A tag means something different each week, and
# the weekly vulnerability scan cannot say anything useful about a moving
# target — the same finding that pinned this repo's music21 dependency and the
# eightbitsaxlounge base images.
FROM python:3.12-slim@sha256:3949e4271b0a3ff82afac7306764c313dcc8edeeb89c0376a3c2ac6007c66b1d

# uid 1000 explicitly. The Deployment sets runAsNonRoot with runAsUser: 1000,
# and a securityContext naming a uid the image does not have is a pod that
# starts as a stranger in its own filesystem. Created here so the two agree.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app

WORKDIR /app

# musicxml-tools first: composer declares it as a dependency by name, and pip
# finds it already satisfied. The build context is services/, which is what
# makes both packages reachable from one Dockerfile.
COPY musicxml-tools/ /tmp/musicxml-tools
RUN pip install --no-cache-dir /tmp/musicxml-tools && rm -rf /tmp/musicxml-tools

COPY composer/pyproject.toml composer/version.txt ./
COPY composer/src/ src/

RUN pip install --no-cache-dir .

USER 1000

EXPOSE 8000

CMD ["uvicorn", "composer.app:app", "--host", "0.0.0.0", "--port", "8000"]
