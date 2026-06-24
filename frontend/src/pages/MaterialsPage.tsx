import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useQuizStore } from "../store/quizStore";
import FileUpload from "../components/FileUpload";

export default function MaterialsPage() {
  const [studentId, setStudentId] = useState("student-1");
  const { createSession, loading, error } = useQuizStore();
  const navigate = useNavigate();

  async function handleStartQuiz(materialId: string) {
    const sid = await createSession(materialId, { studentId });
    if (sid) navigate(`/quiz/${sid}`);
  }

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">学习材料</h1>
      <p className="text-sm text-gray-500 mb-6">
        上传新的学习材料或选择已有材料创建测验
      </p>

      <div className="mb-4">
        <label className="text-xs text-gray-500">学生 ID</label>
        <input
          type="text"
          className="border border-gray-300 rounded p-2 text-sm ml-2 w-48"
          value={studentId}
          onChange={(e) => setStudentId(e.target.value)}
        />
      </div>

      {error && (
        <div className="bg-red-50 text-danger text-sm p-3 rounded mb-4">
          {error}
        </div>
      )}

      <FileUpload onUploaded={handleStartQuiz} />
    </div>
  );
}
