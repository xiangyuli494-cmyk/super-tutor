import type { QuestionResponse } from "../api/types";

interface Props {
  question: QuestionResponse;
  selected: unknown;
  disabled: boolean;
  onSelect: (questionId: string, answer: string) => void;
}

export default function QuizCard({ question, selected, disabled, onSelect }: Props) {
  const isMultipleChoice = question.type === "multiple_choice";

  return (
    <div className="bg-white rounded-lg shadow p-5 mb-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-medium bg-primary-100 text-primary-700 px-2 py-0.5 rounded">
          {question.type === "multiple_choice" ? "选择题" : "简答题"}
        </span>
        <span className="text-xs text-gray-400">
          {question.points} 分 · ~{question.estimated_seconds}s
        </span>
      </div>

      <h3 className="text-base font-medium mb-4">{question.stem}</h3>

      {isMultipleChoice && question.options.length > 0 ? (
        <div className="space-y-2">
          {question.options.map((opt) => (
            <label
              key={opt.key}
              className={`flex items-center gap-3 p-3 border rounded cursor-pointer transition ${
                selected === opt.key
                  ? "border-primary-500 bg-primary-50"
                  : "border-gray-200 hover:border-gray-300"
              } ${disabled ? "pointer-events-none opacity-60" : ""}`}
            >
              <input
                type="radio"
                name={question.question_id}
                value={opt.key}
                checked={selected === opt.key}
                onChange={() => onSelect(question.question_id, opt.key)}
                disabled={disabled}
                className="accent-primary-600"
              />
              <span className="text-sm">
                <span className="font-medium mr-1">{opt.key}.</span>
                {opt.text}
              </span>
            </label>
          ))}
        </div>
      ) : (
        <input
          type="text"
          className="w-full border border-gray-300 rounded p-2 text-sm"
          placeholder="输入你的答案..."
          value={(selected as string) || ""}
          onChange={(e) => onSelect(question.question_id, e.target.value)}
          disabled={disabled}
        />
      )}
    </div>
  );
}
