#!/bin/bash
#SBATCH -J bibrec
#SBATCH -p hestia
#SBATCH -o pipeline/bibtex_reconstruction/logs/%x_%j.log
##SBATCH -t 1-00:00:00
#SBATCH -c 8
#SBATCH --mem=60G
#SBATCH --gpus=1
#SBATCH --signal=B:TERM@60

set -Eeuo pipefail

submit_dir="${SLURM_SUBMIT_DIR:-$(pwd)}"
repo_root=$(git -C "${submit_dir}" rev-parse --show-toplevel)

cd "${repo_root}"

project_dir="pipeline/bibtex_reconstruction"
data_dir="${project_dir}/data"
data_logs_dir="${data_dir}/logs"
input_path="${BIBTEX_RECONSTRUCTION_INPUT_PATH:-${data_dir}/input.json}"
output_path="${BIBTEX_RECONSTRUCTION_OUTPUT_PATH:-${data_dir}/reconstructed.bib}"
report_path="${BIBTEX_RECONSTRUCTION_REPORT_PATH:-${data_dir}/reconstruction-report.json}"
vllm_pid=""

cleanup() {
    exit_code=$?
    trap - EXIT INT TERM
    if [ -n "${vllm_pid}" ] && kill -0 "${vllm_pid}" 2>/dev/null; then
        kill "${vllm_pid}" 2>/dev/null || true
        wait "${vllm_pid}" 2>/dev/null || true
    fi
    exit "${exit_code}"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

echo "Slurm job ID: ${SLURM_JOB_ID:-unknown}"
echo "Node: $(hostname)"
nvidia-smi \
    --query-gpu=name,memory.total,driver_version \
    --format=csv

if ! command -v uv >/dev/null 2>&1; then
    echo "uv was not found." >&2
    exit 1
fi

if [ ! -f "${input_path}" ]; then
    echo "Input file not found: ${input_path}" >&2
    exit 1
fi

gpu_count=$(nvidia-smi -L | wc -l | tr -d ' ')
if [ "${gpu_count}" -lt 1 ]; then
    echo "No visible NVIDIA GPU was found." >&2
    exit 1
fi

mkdir -p "${data_logs_dir}"
run_timestamp=$(date "+%Y%m%d-%H%M%S")
detail_log="${data_logs_dir}/reconstruction-${run_timestamp}-${SLURM_JOB_ID:-$$}.log"
ln -sfn "$(basename "${detail_log}")" "${data_logs_dir}/latest.log"

export BIBTEX_RECONSTRUCTION_LOCAL_LLM_ENABLED=true
export BIBTEX_RECONSTRUCTION_LOCAL_LLM_MODEL=Qwen/Qwen3-32B-AWQ
export BIBTEX_RECONSTRUCTION_LOCAL_LLM_BASE_URL=http://127.0.0.1:8001/v1
export BIBTEX_RECONSTRUCTION_REMOTE_LLM_FALLBACK_ENABLED=false
export BIBTEX_RECONSTRUCTION_CONCEPT_RANKING_BATCH_SIZE=32

model="${BIBTEX_RECONSTRUCTION_LOCAL_LLM_MODEL}"
host=127.0.0.1
port=8001
tensor_parallel_size=1
max_model_len=8192
max_num_seqs=8
gpu_memory_utilization=0.85

echo "Synchronizing the locked CUDA 12.9 environment..."
uv sync \
    --project "${project_dir}" \
    --frozen

uv run \
    --project "${project_dir}" \
    --frozen \
    --no-sync \
    python -c \
    'from importlib.metadata import version; import torch; vllm_version = version("vllm"); assert torch.version.cuda == "12.9"; assert vllm_version.endswith("+cu129"); print(f"torch={torch.__version__} bundled_cuda={torch.version.cuda} vllm={vllm_version}")'

echo "Starting local vLLM model=${model} tp=${tensor_parallel_size} port=${port}"
uv run \
    --project "${project_dir}" \
    --frozen \
    --no-sync \
    vllm serve "${model}" \
    --served-model-name "${model}" \
    --host "${host}" \
    --port "${port}" \
    --tensor-parallel-size "${tensor_parallel_size}" \
    --dtype bfloat16 \
    --quantization awq \
    --gpu-memory-utilization "${gpu_memory_utilization}" \
    --max-model-len "${max_model_len}" \
    --max-num-seqs "${max_num_seqs}" \
    --enable-prefix-caching \
    --disable-log-requests \
    --generation-config vllm \
    --default-chat-template-kwargs '{"enable_thinking": false}' &
vllm_pid=$!

ready=0
startup_timeout_sec="${BIBTEX_RECONSTRUCTION_VLLM_STARTUP_TIMEOUT_SEC:-3600}"
startup_interval_sec="${BIBTEX_RECONSTRUCTION_VLLM_STARTUP_INTERVAL_SEC:-10}"
startup_deadline=$((SECONDS + startup_timeout_sec))
attempt=0

while ((SECONDS < startup_deadline)); do
    attempt=$((attempt + 1))
    if ! kill -0 "${vllm_pid}" 2>/dev/null; then
        echo "vLLM exited before becoming ready." >&2
        server_status=1
        wait "${vllm_pid}" || server_status=$?
        exit "${server_status}"
    fi

    if uv run \
        --project "${project_dir}" \
        --frozen \
        --no-sync \
        bibtex-vllm-check; then
        ready=1
        break
    fi

    elapsed_sec=$((startup_timeout_sec - startup_deadline + SECONDS))
    echo "Waiting for vLLM: attempt=${attempt} elapsed=${elapsed_sec}s"
    sleep "${startup_interval_sec}"
done

if [ "${ready}" -ne 1 ]; then
    echo "vLLM did not become ready within ${startup_timeout_sec}s." >&2
    exit 1
fi

echo "vLLM is ready; starting BibTeX reconstruction and key generation."
echo "Detailed log: ${detail_log}"

uv run \
    --project "${project_dir}" \
    --frozen \
    --no-sync \
    bibtex-reconstruction \
    "${input_path}" \
    "$@" \
    --output "${output_path}" \
    --report-output "${report_path}" \
    --log-file "${detail_log}"
