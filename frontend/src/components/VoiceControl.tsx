import { ConnectionStatus, PipelineStatus } from '../hooks/useWebRTC';

interface VoiceControlProps {
  connectionStatus: ConnectionStatus;
  pipelineStatus: PipelineStatus;
  onConnect: () => void;
  onDisconnect: () => void;
  disabled?: boolean;
}

export function VoiceControl({
  connectionStatus,
  pipelineStatus,
  onConnect,
  onDisconnect,
  disabled,
}: VoiceControlProps) {
  const isConnected = connectionStatus === 'connected';
  const isConnecting = connectionStatus === 'connecting';

  return (
    <div className="flex flex-col items-center gap-4">
      {/* Main connect/disconnect button */}
      <button
        onClick={isConnected ? onDisconnect : onConnect}
        disabled={isConnecting || disabled}
        className={`
          relative w-24 h-24 rounded-full font-semibold transition-all duration-300
          flex items-center justify-center
          ${isConnected
            ? 'bg-red-600 hover:bg-red-700 text-white'
            : 'bg-camb-orange hover:bg-camb-orange-hover text-white'
          }
          ${isConnecting ? 'opacity-50 cursor-wait' : ''}
          ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
          disabled:hover:bg-current
        `}
      >
        {/* Pulsing ring when speaking */}
        {isConnected && pipelineStatus === 'tts' && (
          <span className="absolute inset-0 rounded-full bg-red-500 animate-ping opacity-25" />
        )}

        {isConnecting ? (
          <div className="w-8 h-8 border-3 border-white border-t-transparent rounded-full animate-spin" />
        ) : isConnected ? (
          <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        ) : (
          <svg className="w-10 h-10" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z"
            />
          </svg>
        )}
      </button>

      {/* Status text */}
      <div className="text-center">
        <p className="text-lg font-medium">
          {isConnecting
            ? 'Connecting...'
            : isConnected
            ? 'Connected'
            : 'Disconnected'}
        </p>
        {isConnected && (
          <p className="text-sm text-gray-500 mt-1">
            Click to end call
          </p>
        )}
        {!isConnected && !isConnecting && (
          <p className="text-sm text-gray-500 mt-1">
            Click to start voice chat
          </p>
        )}
      </div>

      {/* Audio visualizer when speaking */}
      {isConnected && (pipelineStatus === 'listening' || pipelineStatus === 'tts') && (
        <div className="flex items-end justify-center gap-1 h-8">
          {[...Array(5)].map((_, i) => (
            <div
              key={i}
              className={`w-1 rounded-full audio-bar ${
                pipelineStatus === 'tts' ? 'bg-camb-orange' : 'bg-camb-orange-light'
              }`}
              style={{ animationDelay: `${i * 0.1}s` }}
            />
          ))}
        </div>
      )}
    </div>
  );
}
