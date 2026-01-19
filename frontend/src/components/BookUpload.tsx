import { useState, useRef } from 'react';

interface BookUploadProps {
  sessionId: string | null;
  onUploadSuccess: (filename: string) => void;
  disabled?: boolean;
}

interface UploadState {
  isUploading: boolean;
  error: string | null;
  uploadedFile: string | null;
}

export function BookUpload({ sessionId, onUploadSuccess, disabled }: BookUploadProps) {
  const [state, setState] = useState<UploadState>({
    isUploading: false,
    error: null,
    uploadedFile: null,
  });
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFile = async (file: File) => {
    if (!sessionId) {
      setState((s) => ({ ...s, error: 'No session ID' }));
      return;
    }

    // Validate file type
    const validTypes = ['.pdf', '.txt'];
    const extension = file.name.toLowerCase().slice(file.name.lastIndexOf('.'));
    if (!validTypes.includes(extension)) {
      setState((s) => ({ ...s, error: 'Please upload a PDF or TXT file' }));
      return;
    }

    setState({ isUploading: true, error: null, uploadedFile: null });

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`/api/session/${sessionId}/upload-book`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Upload failed');
      }

      const result = await response.json();
      setState({
        isUploading: false,
        error: null,
        uploadedFile: result.filename,
      });
      onUploadSuccess(result.filename);
    } catch (error) {
      setState({
        isUploading: false,
        error: error instanceof Error ? error.message : 'Upload failed',
        uploadedFile: null,
      });
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);

    const file = e.dataTransfer.files[0];
    if (file) {
      handleFile(file);
    }
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => {
    setIsDragging(false);
  };

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      handleFile(file);
    }
  };

  const handleClear = async () => {
    if (!sessionId) return;

    try {
      await fetch(`/api/session/${sessionId}/clear-book`, {
        method: 'POST',
      });
      setState({ isUploading: false, error: null, uploadedFile: null });
    } catch (error) {
      console.error('Failed to clear book:', error);
    }
  };

  return (
    <div className="w-full">
      <h2 className="text-lg font-semibold mb-3 text-gray-200">Upload Book</h2>

      {state.uploadedFile ? (
        <div className="bg-camb-card border border-green-700/50 rounded-xl p-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <svg
                className="w-8 h-8 text-green-500"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              <div>
                <p className="font-medium text-green-400">{state.uploadedFile}</p>
                <p className="text-sm text-gray-500">Uploaded to Gemini - Ready for Q&A</p>
              </div>
            </div>
            <button
              onClick={handleClear}
              disabled={disabled}
              className="text-gray-500 hover:text-white transition-colors disabled:opacity-50"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M6 18L18 6M6 6l12 12"
                />
              </svg>
            </button>
          </div>
        </div>
      ) : (
        <div
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => fileInputRef.current?.click()}
          className={`
            bg-camb-card border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors
            ${isDragging ? 'border-camb-orange bg-camb-orange/10' : 'border-camb-border hover:border-camb-orange/50'}
            ${state.isUploading ? 'opacity-50 cursor-wait' : ''}
          `}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.txt"
            onChange={handleInputChange}
            className="hidden"
            disabled={state.isUploading || disabled}
          />

          {state.isUploading ? (
            <div className="flex flex-col items-center gap-2">
              <div className="w-8 h-8 border-2 border-camb-orange border-t-transparent rounded-full animate-spin" />
              <p className="text-gray-400">Uploading to Gemini...</p>
            </div>
          ) : (
            <>
              <svg
                className="w-12 h-12 mx-auto text-gray-600 mb-3"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"
                />
              </svg>
              <p className="text-gray-300 mb-1">Drop your book here or click to browse</p>
              <p className="text-sm text-gray-500">Supports PDF and TXT files</p>
            </>
          )}
        </div>
      )}

      {state.error && (
        <p className="mt-2 text-sm text-red-400">{state.error}</p>
      )}
    </div>
  );
}
