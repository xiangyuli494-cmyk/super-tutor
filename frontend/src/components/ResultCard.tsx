import type { AttemptResult } from "../api/types";

interface Props {
  attempt: AttemptResult;
  index: number;
}

export default function ResultCard({ attempt, index }: Props) {
  return (
    <div
      className={`bg-white rounded-lg shadow p-4 mb-3 border-l-4 ${
        attempt.is_correct ? "border-success" : "border-danger"
      }`}
    >
      <div className="flex items-center justify-between mb-2">
        <span className="font-medium text-sm">第 {index + 1} 题</span>
        <span
          className={`text-xs font-bold px-2 py-0.5 rounded ${
            attempt.is_correct
              ? "bg-green-100 text-green-700"
              : "bg-red-100 text-red-700"
          }`}
        >
          {attempt.is_correct ? "正确" : "错误"} · {attempt.score} 分
        </span>
      </div>
      <p className="text-sm text-gray-500 mb-1">
        你的答案:{" "}
        <span className="font-medium text-gray-800">
          {String(attempt.student_answer ?? "(空)")}
        </span>
      </p>
      {attempt.explanation && (
        <p className="text-xs text-gray-500 mt-2">{attempt.explanation}</p>
      )}
    </div>
  );
}
