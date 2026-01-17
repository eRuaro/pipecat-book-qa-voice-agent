import { useState, useEffect, useCallback } from 'react';
import { BookUpload } from './components/BookUpload';
import { VoiceControl } from './components/VoiceControl';
import { StatusIndicator } from './components/StatusIndicator';
import { ChatInterface } from './components/ChatInterface';
import { useWebRTC, TranscriptMessage, LogMessage, PipelineStatus } from './hooks/useWebRTC';

type TTSModel = 'mars-flash' | 'mars-pro';

function App() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [bookInfo, setBookInfo] = useState<{ filename: string } | null>(null);
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [logs, setLogs] = useState<LogMessage[]>([]);
  const [currentText, setCurrentText] = useState<string>('');
  const [ttsModel, setTtsModel] = useState<TTSModel>('mars-flash');

  // Create session on mount
  useEffect(() => {
    const createSession = async () => {
      try {
        const response = await fetch('/api/session', { method: 'POST' });
        const data = await response.json();
        setSessionId(data.session_id);
      } catch (error) {
        console.error('Failed to create session:', error);
      }
    };

    createSession();
  }, []);

  // Handle status changes
  const handleStatusChange = useCallback((status: PipelineStatus) => {
    // Clear current text when switching away from STT
    if (status !== 'stt' && status !== 'listening') {
      setCurrentText('');
    }
  }, []);

  // Handle transcript updates - supports streaming
  const handleTranscript = useCallback((message: TranscriptMessage) => {
    console.log('[App] handleTranscript called:', message);
    setMessages((prev) => {
      // Check if this is an update to an existing message
      const existingIndex = prev.findIndex((m) => m.id === message.id);
      if (existingIndex >= 0) {
        // Update existing message
        const updated = [...prev];
        updated[existingIndex] = message;
        console.log('[App] Updated existing message at index:', existingIndex);
        return updated;
      }
      // Add new message
      console.log('[App] Adding new message, total will be:', prev.length + 1);
      return [...prev, message];
    });
  }, []);

  // Handle log updates
  const handleLog = useCallback((log: LogMessage) => {
    setLogs((prev) => [...prev.slice(-19), log]); // Keep last 20 logs
  }, []);

  // WebRTC hook
  const {
    connectionStatus,
    pipelineStatus,
    connect,
    disconnect,
    isConnected,
    isMuted,
    toggleMute,
  } = useWebRTC({
    sessionId,
    ttsModel,
    onStatusChange: handleStatusChange,
    onTranscript: handleTranscript,
    onLog: handleLog,
  });

  // Handle book upload success
  const handleUploadSuccess = (filename: string) => {
    setBookInfo({ filename });
  };

  // Clear logs and messages when disconnected
  useEffect(() => {
    if (!isConnected) {
      setLogs([]);
      setMessages([]);
    }
  }, [isConnected]);

  return (
    <div className="min-h-screen bg-gray-900 text-white flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold">Book Q&A Voice Agent</h1>
            <p className="text-sm text-gray-400">Powered by CAMB AI + Pipecat</p>
          </div>
          {sessionId && (
            <div className="text-xs text-gray-600">
              Session: {sessionId.slice(0, 8)}...
            </div>
          )}
        </div>
      </header>

      {/* Main content */}
      <main className="flex-1 max-w-6xl mx-auto p-6 w-full">
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Left column - Book upload and status */}
          <div className="space-y-6">
            <BookUpload
              sessionId={sessionId}
              onUploadSuccess={handleUploadSuccess}
              disabled={isConnected}
            />

            <StatusIndicator status={pipelineStatus} isConnected={isConnected} />

            {/* TTS Model Toggle */}
            <div className="bg-gray-800 rounded-lg p-4">
              <h3 className="text-sm font-medium text-gray-300 mb-3">Voice Model</h3>
              <div className="flex gap-2">
                <button
                  onClick={() => setTtsModel('mars-flash')}
                  disabled={connectionStatus !== 'disconnected'}
                  className={`flex-1 px-3 py-2 text-sm rounded-lg transition-colors ${
                    ttsModel === 'mars-flash'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  } ${connectionStatus !== 'disconnected' ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  Flash
                  <span className="block text-xs opacity-70">Fast</span>
                </button>
                <button
                  onClick={() => setTtsModel('mars-pro')}
                  disabled={connectionStatus !== 'disconnected'}
                  className={`flex-1 px-3 py-2 text-sm rounded-lg transition-colors ${
                    ttsModel === 'mars-pro'
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  } ${connectionStatus !== 'disconnected' ? 'opacity-50 cursor-not-allowed' : ''}`}
                >
                  Pro
                  <span className="block text-xs opacity-70">Quality</span>
                </button>
              </div>
            </div>
          </div>

          {/* Center column - Voice control */}
          <div className="flex flex-col items-center justify-center py-8">
            <VoiceControl
              connectionStatus={connectionStatus}
              pipelineStatus={pipelineStatus}
              onConnect={connect}
              onDisconnect={disconnect}
              disabled={!sessionId}
            />

            {/* Mute button - only show when connected */}
            {isConnected && (
              <button
                onClick={toggleMute}
                className={`mt-4 px-4 py-2 rounded-lg flex items-center gap-2 transition-colors ${
                  isMuted
                    ? 'bg-red-600 hover:bg-red-700 text-white'
                    : 'bg-gray-700 hover:bg-gray-600 text-gray-200'
                }`}
              >
                {isMuted ? (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" />
                  </svg>
                ) : (
                  <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                  </svg>
                )}
                {isMuted ? 'Unmute' : 'Mute'}
              </button>
            )}

            {!bookInfo && !isConnected && (
              <p className="mt-6 text-sm text-gray-500 text-center max-w-xs">
                Upload a book first to get the best experience, or connect to chat without one.
              </p>
            )}

            {currentText && (
              <div className="mt-6 bg-gray-800 rounded-lg p-3 max-w-xs">
                <p className="text-sm text-gray-300 italic">"{currentText}"</p>
              </div>
            )}
          </div>

          {/* Right column - Chat */}
          <div className="h-[500px]">
            <ChatInterface messages={messages} isConnected={isConnected} />
          </div>
        </div>
      </main>

      {/* Footer with logs */}
      <footer className="border-t border-gray-800 px-6 py-3">
        <div className="max-w-6xl mx-auto">
          <div className="flex items-center justify-between mb-2">
            <p className="text-xs text-gray-500">
              Voice powered by CAMB AI mars-flash | Built with Pipecat + Gemini Flash
            </p>
            {isConnected && logs.length > 0 && (
              <span className="text-xs text-green-500 flex items-center gap-1">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Live
              </span>
            )}
          </div>
          {isConnected && (
            <div className="bg-gray-800/50 rounded p-2 font-mono text-xs text-gray-400 h-32 overflow-y-auto">
              {logs.length === 0 ? (
                <span className="text-gray-600">Waiting for activity...</span>
              ) : (
                logs.map((log, i) => (
                  <div key={i} className="flex gap-2">
                    <span className="text-gray-600">
                      {new Date(log.timestamp).toLocaleTimeString()}
                    </span>
                    <span>{log.text}</span>
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      </footer>
    </div>
  );
}

export default App;
