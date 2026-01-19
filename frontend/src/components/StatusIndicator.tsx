import { PipelineStatus } from '../hooks/useWebRTC';

interface StatusIndicatorProps {
  status: PipelineStatus;
  isConnected: boolean;
}

interface Stage {
  id: PipelineStatus;
  label: string;
  description: string;
}

const stages: Stage[] = [
  { id: 'stt', label: 'STT', description: 'Listening' },
  { id: 'llm', label: 'LLM', description: 'Thinking' },
  { id: 'tts', label: 'TTS', description: 'Speaking' },
];

export function StatusIndicator({ status, isConnected }: StatusIndicatorProps) {
  if (!isConnected) {
    return (
      <div className="bg-camb-card border border-camb-border rounded-xl p-4">
        <p className="text-center text-gray-500">Connect to see pipeline status</p>
      </div>
    );
  }

  const getStageState = (stage: Stage): 'inactive' | 'active' | 'completed' => {
    const stageOrder = ['stt', 'llm', 'tts'];
    const currentIndex = stageOrder.indexOf(status);
    const stageIndex = stageOrder.indexOf(stage.id);

    if (status === 'idle' || status === 'listening') return 'inactive';
    if (stage.id === status) return 'active';
    if (stageIndex < currentIndex) return 'completed';
    return 'inactive';
  };

  return (
    <div className="bg-camb-card border border-camb-border rounded-xl p-4">
      <h3 className="text-sm font-medium text-gray-400 mb-4 text-center">Pipeline Status</h3>

      <div className="flex items-center justify-center gap-2">
        {stages.map((stage, index) => {
          const state = getStageState(stage);
          const isActive = state === 'active';
          const isCompleted = state === 'completed';

          return (
            <div key={stage.id} className="flex items-center">
              {/* Stage indicator */}
              <div className="flex flex-col items-center">
                <div
                  className={`
                    w-12 h-12 rounded-full flex items-center justify-center font-medium text-sm
                    transition-all duration-300
                    ${isActive ? 'bg-camb-orange text-white status-active' : ''}
                    ${isCompleted ? 'bg-green-600 text-white' : ''}
                    ${!isActive && !isCompleted ? 'bg-camb-bg border border-camb-border text-gray-500' : ''}
                  `}
                >
                  {isCompleted ? (
                    <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    stage.label
                  )}
                </div>
                <span
                  className={`
                    text-xs mt-2 transition-colors
                    ${isActive ? 'text-camb-orange' : ''}
                    ${isCompleted ? 'text-green-400' : ''}
                    ${!isActive && !isCompleted ? 'text-gray-500' : ''}
                  `}
                >
                  {isActive ? stage.description : stage.label}
                </span>
              </div>

              {/* Connector line */}
              {index < stages.length - 1 && (
                <div
                  className={`
                    w-8 h-0.5 mx-2 transition-colors
                    ${isCompleted ? 'bg-green-600' : 'bg-camb-border'}
                  `}
                />
              )}
            </div>
          );
        })}
      </div>

      {/* Current status text */}
      <p className="text-center text-sm text-gray-500 mt-4">
        {status === 'idle' && 'Waiting for input...'}
        {status === 'listening' && 'Listening to you...'}
        {status === 'stt' && 'Processing speech...'}
        {status === 'llm' && 'Generating response...'}
        {status === 'tts' && 'Speaking...'}
      </p>
    </div>
  );
}
