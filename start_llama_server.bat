@echo off
echo Starting llama-server on port 8081...
echo Model: F:\BackUp\Projects\Piper\models\llama\Qwen3.5-4B-Q8_0.gguf
echo.
"C:\Projects\Piper\runtime\llama.cpp\llama-server.exe" -m "F:\BackUp\Projects\Piper\models\llama\Qwen3.5-4B-Q8_0.gguf" --port 8081 --host 0.0.0.0 -ngl 99 -c 8192
pause
