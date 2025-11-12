import React, { useRef, useState } from 'react';
import { Loader2, UploadCloud } from 'lucide-react';
import GlassCard from '../ui/GlassCard';

type WorkflowPriority = 'low' | 'normal' | 'high';

interface UploadPanelProps {
  isUploading: boolean;
  onUploadFile: (file: File, priority: WorkflowPriority) => Promise<void> | void;
  onSubmitManualList: (companyList: string, priority: WorkflowPriority) => Promise<void> | void;
}

const UploadPanel: React.FC<UploadPanelProps> = ({
  isUploading,
  onUploadFile,
  onSubmitManualList,
}) => {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [manualList, setManualList] = useState('');
  const [priority, setPriority] = useState<WorkflowPriority>('normal');

  const handleFileSelect = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) {
      return;
    }
    await onUploadFile(file, priority);
    event.target.value = '';
  };

  const handleManualSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!manualList.trim()) {
      return;
    }
    await onSubmitManualList(manualList.trim(), priority);
    setManualList('');
  };

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-foreground">Schedule new workflow</h2>
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          Priority
          <select
            value={priority}
            onChange={(event) => setPriority(event.target.value as WorkflowPriority)}
            className="rounded border border-border/40 bg-background/80 px-2 py-1 text-sm"
          >
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
          </select>
        </div>
      </div>

      <GlassCard className="grid gap-4 p-6 lg:grid-cols-2">
        <div className="flex flex-col gap-3 rounded-lg border border-dashed border-border/40 p-6 text-center">
          <UploadCloud className="mx-auto h-10 w-10 text-primary" />
          <p className="text-sm text-muted-foreground">
            Upload a CSV with company names or prospect records and Link will enrich, deduplicate,
            and route to the appropriate workflow.
          </p>
          <div className="flex justify-center">
            <button
              type="button"
              disabled={isUploading}
              onClick={() => fileInputRef.current?.click()}
              className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground shadow-sm transition-colors hover:bg-primary/90 disabled:cursor-not-allowed disabled:opacity-70"
            >
              {isUploading && <Loader2 className="h-4 w-4 animate-spin" />}
              Upload CSV
            </button>
          </div>
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            className="hidden"
            onChange={handleFileSelect}
          />
        </div>

        <form onSubmit={handleManualSubmit} className="flex flex-col gap-3">
          <label className="text-sm font-medium text-foreground">
            Add company list manually
            <textarea
              value={manualList}
              onChange={(event) => setManualList(event.target.value)}
              placeholder="Acme Corp&#10;Northern Lights Analytics&#10;FutureSight Labs"
              className="mt-2 min-h-[140px] rounded-lg border border-border/30 bg-background/80 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/30"
            />
          </label>
          <button
            type="submit"
            disabled={isUploading || !manualList.trim()}
            className="self-end inline-flex items-center gap-2 rounded-lg border border-primary/30 px-4 py-2 text-sm font-semibold text-primary transition-colors hover:bg-primary/10 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {isUploading && <Loader2 className="h-4 w-4 animate-spin" />}
            Queue workflow
          </button>
        </form>
      </GlassCard>
    </section>
  );
};

export default UploadPanel;
