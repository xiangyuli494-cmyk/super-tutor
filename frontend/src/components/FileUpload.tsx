import { useRef, useState } from "react";
import * as api from "../api/client";

interface Props {
  onUploaded?: (materialId: string, title: string) => void;
}

export default function FileUpload({ onUploaded }: Props) {
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [subject, setSubject] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  async function handleTextUpload() {
    if (!title.trim() || !content.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const resp = await api.uploadMaterial({
        title: title.trim(),
        content: content.trim(),
        subject: subject.trim(),
      });
      setTitle("");
      setContent("");
      setSubject("");
      onUploaded?.(resp.data.material_id, resp.data.title);
    } catch (e: unknown) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="bg-white rounded-lg shadow p-5">
      <h2 className="font-semibold mb-4">上传学习材料</h2>

      <div className="space-y-3">
        <input
          type="text"
          className="w-full border border-gray-300 rounded p-2 text-sm"
          placeholder="材料标题（如：大学物理·力学篇）"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <input
          type="text"
          className="w-full border border-gray-300 rounded p-2 text-sm"
          placeholder="学科（可选，如：物理）"
          value={subject}
          onChange={(e) => setSubject(e.target.value)}
        />
        <textarea
          className="w-full border border-gray-300 rounded p-2 text-sm min-h-[120px]"
          placeholder="粘贴材料内容（Markdown 或纯文本）..."
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
        <button
          className="bg-primary-600 text-white px-4 py-2 rounded text-sm hover:bg-primary-700 disabled:opacity-50"
          disabled={loading || !title.trim() || !content.trim()}
          onClick={handleTextUpload}
        >
          {loading ? "上传中..." : "上传文本材料"}
        </button>

        <div className="relative text-center text-xs text-gray-400 py-2">
          — 或 —
        </div>

        <input
          ref={fileRef}
          type="file"
          accept=".pdf"
          className="text-sm"
          onChange={async (e) => {
            const file = e.target.files?.[0];
            if (!file) return;
            if (file.size > 50 * 1024 * 1024) {
              setError("文件大小不能超过 50MB");
              return;
            }
            setLoading(true);
            setError(null);
            try {
              const resp = await api.uploadPdfFile(
                file,
                title.trim() || file.name.replace(/\.pdf$/i, ""),
                subject.trim()
              );
              setTitle("");
              setSubject("");
              onUploaded?.(resp.data.material_id, resp.data.title);
            } catch (e: unknown) {
              setError((e as Error).message);
            } finally {
              setLoading(false);
            }
          }}
        />
      </div>

      {error && (
        <p className="text-danger text-xs mt-3">{error}</p>
      )}
    </div>
  );
}
