import { BookOpen, RefreshCw } from "lucide-react";
import { uiText } from "../schemas/ui";

interface AppFooterProps {
  onRefresh: () => void;
}

export function AppFooter({ onRefresh }: AppFooterProps) {
  return (
    <footer className="footer">
      <div>
        <BookOpen size={15} /> {uiText.header.appName} <span>·</span>{" "}
        {uiText.footer.privateWorkspace}
      </div>
      <button onClick={onRefresh} type="button">
        <RefreshCw size={13} /> {uiText.footer.refreshStatus}
      </button>
    </footer>
  );
}
