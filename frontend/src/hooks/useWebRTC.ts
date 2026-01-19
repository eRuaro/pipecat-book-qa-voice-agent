import { useState, useRef, useCallback, useEffect } from 'react';

export type ConnectionStatus = 'disconnected' | 'connecting' | 'connected';
export type PipelineStatus = 'idle' | 'listening' | 'stt' | 'llm' | 'tts';

export interface TranscriptMessage {
  id: string;  // Composite ID: "role-messageId" to prevent collisions
  role: 'user' | 'assistant';
  text: string;
  timestamp: number;  // Server timestamp for ordering
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

  const peerConnectionRef = useRef<RTCPeerConnection | null>(null);
  const dataChannelRef = useRef<RTCDataChannel | null>(null);
  const localStreamRef = useRef<MediaStream | null>(null);
  const pcIdRef = useRef<string | null>(null);

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

  // Handle incoming messages from the server
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data = JSON.parse(event.data);
      console.log('[WebRTC] Received message:', data.type, data);

      if (data.type === 'status') {
        const status = data.status as PipelineStatus;
        setPipelineStatus(status);
        onStatusChangeRef.current?.(status);
      } else if (data.type === 'transcript') {
        // Handle streaming transcripts
        // Create composite ID using role to prevent collisions between user and assistant messages
        const role = data.role as 'user' | 'assistant';
        let messageId: number;
        if (data.messageId != null) {
          messageId = data.messageId;
        } else {
          // Fallback: generate unique ID per role
          messageId = role === 'user' ? ++globalUserMessageId : ++globalAssistantMessageId;
        }
        const compositeId = `${role}-${messageId}`;

        const message: TranscriptMessage = {
          id: compositeId,
          role,
          text: data.text,
          timestamp: data.timestamp ?? Date.now(),  // Prefer server timestamp
          final: data.final ?? true,
        };
        console.log('[WebRTC] Transcript message:', message);
        onTranscriptRef.current?.(message);
      } else if (data.type === 'log') {
        const log: LogMessage = {
          text: data.text,
          timestamp: Date.now(),
        };
        onLogRef.current?.(log);
      }
    } catch (e) {
      console.error('Error parsing message:', e);
    }
  }, []); // No dependencies needed - using refs

  // Disconnect from the server - defined before connect so it can be referenced
  const disconnect = useCallback(() => {
    if (dataChannelRef.current) {
      dataChannelRef.current.close();
      dataChannelRef.current = null;
    }

    if (peerConnectionRef.current) {
      peerConnectionRef.current.close();
      peerConnectionRef.current = null;
    }

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach((track) => track.stop());
      localStreamRef.current = null;
    }

    pcIdRef.current = null;
    setConnectionStatus('disconnected');
    setPipelineStatus('idle');
  }, []);

  // Connect to the WebRTC server
  const connect = useCallback(async () => {
    if (connectionStatus !== 'disconnected') return;

    setConnectionStatus('connecting');

    try {
      // Fetch ICE servers config from backend (includes TURN if configured)
      let iceServers: RTCIceServer[] = [{ urls: 'stun:stun.l.google.com:19302' }];
      try {
        const iceResponse = await fetch('/api/ice-servers');
        const iceConfig = await iceResponse.json();
        if (iceConfig.iceServers) {
          iceServers = iceConfig.iceServers;
        }
      } catch (e) {
        console.warn('Failed to fetch ICE servers, using default STUN only:', e);
      }

      // Get microphone access
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      localStreamRef.current = stream;

      // Create peer connection with fetched ICE servers
      const pc = new RTCPeerConnection({ iceServers });
      peerConnectionRef.current = pc;

      // Add audio track
      stream.getTracks().forEach((track) => {
        pc.addTrack(track, stream);
      });

      // Handle incoming audio
      pc.ontrack = (event) => {
        const audio = new Audio();
        audio.srcObject = event.streams[0];
        audio.play().catch(console.error);
      };

      // Create data channel for messages
      const dataChannel = pc.createDataChannel('messages');
      dataChannelRef.current = dataChannel;

      dataChannel.onmessage = handleMessage;
      dataChannel.onopen = () => {
        console.log('Data channel opened');
      };

      // Create and send offer
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);

      // Wait for ICE gathering to complete
      await new Promise<void>((resolve) => {
        if (pc.iceGatheringState === 'complete') {
          resolve();
        } else {
          pc.onicegatheringstatechange = () => {
            if (pc.iceGatheringState === 'complete') {
              resolve();
            }
          };
        }
      });

      // Send offer to server
      const offerUrl = sessionId
        ? `/sessions/${sessionId}/api/offer`
        : '/api/offer';

      const response = await fetch(offerUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sdp: pc.localDescription?.sdp,
          type: pc.localDescription?.type,
          pc_id: pcIdRef.current,
          tts_model: ttsModel,
        }),
      });

      const answer = await response.json();
      pcIdRef.current = answer.pc_id;

      await pc.setRemoteDescription(new RTCSessionDescription(answer));

      setConnectionStatus('connected');
      setPipelineStatus('idle');
    } catch (error) {
      console.error('Connection error:', error);
      setConnectionStatus('disconnected');
      disconnect();
    }
  }, [connectionStatus, sessionId, ttsModel, handleMessage, disconnect]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      disconnect();
    };
  }, [disconnect]);

  // Toggle microphone mute
  const toggleMute = useCallback(() => {
    if (localStreamRef.current) {
      const audioTrack = localStreamRef.current.getAudioTracks()[0];
      if (audioTrack) {
        audioTrack.enabled = !audioTrack.enabled;
        setIsMuted(!audioTrack.enabled);
        console.log('[WebRTC] Microphone muted:', !audioTrack.enabled);
      }
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
