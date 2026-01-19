import { useState, useRef, useCallback, useEffect } from 'react';
import Daily, { DailyCall, DailyEventObjectAppMessage } from '@daily-co/daily-js';

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected';
export type PipelineStatus = 'idle' | 'listening' | 'stt' | 'llm' | 'tts';

export interface TranscriptMessage {
  id: string;
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;
  final: boolean;
}

export interface LogMessage {
  text: string;
  timestamp: number;
}

export interface UseWebRTCOptions {
  sessionId: string | null;
  ttsModel?: 'mars-flash' | 'mars-pro';
  onStatusChange?: (status: PipelineStatus) => void;
  onTranscript?: (message: TranscriptMessage) => void;
  onLog?: (log: LogMessage) => void;
}

export interface UseWebRTCReturn {
  connectionStatus: ConnectionStatus;
  pipelineStatus: PipelineStatus;
  connect: () => Promise<void>;
  disconnect: () => void;
  isConnected: boolean;
  isMuted: boolean;
  toggleMute: () => void;
}

// Separate counters for user and assistant messages to ensure unique IDs
let globalUserMessageId = 0;
let globalAssistantMessageId = 0;

export function useWebRTC({
  sessionId,
  ttsModel = 'mars-flash',
  onStatusChange,
  onTranscript,
  onLog,
}: UseWebRTCOptions): UseWebRTCReturn {
  const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('disconnected');
  const [pipelineStatus, setPipelineStatus] = useState<PipelineStatus>('idle');
  const [isMuted, setIsMuted] = useState(false);

  const callObjectRef = useRef<DailyCall | null>(null);

  // Use refs to avoid stale closure issues with callbacks
  const onStatusChangeRef = useRef(onStatusChange);
  const onTranscriptRef = useRef(onTranscript);
  const onLogRef = useRef(onLog);

  // Keep refs updated
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
    onTranscriptRef.current = onTranscript;
    onLogRef.current = onLog;
  }, [onStatusChange, onTranscript, onLog]);

  // Handle incoming app messages from the bot
  const handleAppMessage = useCallback((event: DailyEventObjectAppMessage) => {
    try {
      const data = event.data as Record<string, unknown>;
      console.log('[Daily] Received app message:', data);

      if (data.type === 'status') {
        const status = data.status as PipelineStatus;
        setPipelineStatus(status);
        onStatusChangeRef.current?.(status);
      } else if (data.type === 'transcript') {
        const role = data.role as 'user' | 'assistant';
        let messageId: number;
        if (data.messageId != null) {
          messageId = data.messageId as number;
        } else {
          messageId = role === 'user' ? ++globalUserMessageId : ++globalAssistantMessageId;
        }
        const compositeId = `${role}-${messageId}`;

        const message: TranscriptMessage = {
          id: compositeId,
          role,
          text: data.text as string,
          timestamp: (data.timestamp as number) ?? Date.now(),
          final: (data.final as boolean) ?? true,
        };
        console.log('[Daily] Transcript message:', message);
        onTranscriptRef.current?.(message);
      } else if (data.type === 'log') {
        const log: LogMessage = {
          text: data.text as string,
          timestamp: Date.now(),
        };
        onLogRef.current?.(log);
      }
    } catch (e) {
      console.error('Error handling app message:', e);
    }
  }, []);

  // Disconnect from the Daily room
  const disconnect = useCallback(async () => {
    if (callObjectRef.current) {
      await callObjectRef.current.leave();
      await callObjectRef.current.destroy();
      callObjectRef.current = null;
    }
    setConnectionStatus('disconnected');
    setPipelineStatus('idle');
  }, []);

  // Connect to the Daily room
  const connect = useCallback(async () => {
    if (connectionStatus !== 'disconnected' || !sessionId) return;

    setConnectionStatus('connecting');

    try {
      // Request room URL and token from backend
      const response = await fetch(`/api/session/${sessionId}/connect`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tts_model: ttsModel }),
      });

      if (!response.ok) {
        throw new Error(`Failed to connect: ${response.statusText}`);
      }

      const { room_url, token } = await response.json();
      console.log('[Daily] Got room URL:', room_url);

      // Create Daily call object
      const callObject = Daily.createCallObject({
        audioSource: true,
        videoSource: false,
      });
      callObjectRef.current = callObject;

      // Set up event handlers
      callObject.on('joined-meeting', () => {
        console.log('[Daily] Joined meeting');
        setConnectionStatus('connected');
        setPipelineStatus('idle');
      });

      callObject.on('left-meeting', () => {
        console.log('[Daily] Left meeting');
        setConnectionStatus('disconnected');
        setPipelineStatus('idle');
      });

      callObject.on('error', (error) => {
        console.error('[Daily] Error:', error);
        setConnectionStatus('disconnected');
        disconnect();
      });

      callObject.on('app-message', handleAppMessage);

      // Handle remote audio
      callObject.on('track-started', (event) => {
        if (event.track?.kind === 'audio' && event.participant && !event.participant.local) {
          console.log('[Daily] Remote audio track started');
          const audio = new Audio();
          audio.srcObject = new MediaStream([event.track]);
          audio.play().catch(console.error);
        }
      });

      // Join the room
      await callObject.join({
        url: room_url,
        token: token,
      });

    } catch (error) {
      console.error('Connection error:', error);
      setConnectionStatus('disconnected');
      await disconnect();
    }
  }, [connectionStatus, sessionId, ttsModel, handleAppMessage, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (callObjectRef.current) {
        callObjectRef.current.leave();
        callObjectRef.current.destroy();
      }
    };
  }, []);

  // Toggle microphone mute
  const toggleMute = useCallback(() => {
    if (callObjectRef.current) {
      const currentMuteState = callObjectRef.current.localAudio() === false;
      callObjectRef.current.setLocalAudio(currentMuteState);
      setIsMuted(!currentMuteState);
      console.log('[Daily] Microphone muted:', !currentMuteState);
    }
  }, []);

  return {
    connectionStatus,
    pipelineStatus,
    connect,
    disconnect,
    isConnected: connectionStatus === 'connected',
    isMuted,
    toggleMute,
  };
}
