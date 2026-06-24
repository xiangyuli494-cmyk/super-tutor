import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useStudentStore } from "../store/studentStore";
import MasteryChart from "../components/MasteryChart";

export default function Dashboard() {
  const {
    studentId,
    dashboard,
    mastery,
    loading,
    error,
    fetchDashboard,
    fetchMastery,
  } = useStudentStore();
  const navigate = useNavigate();

  useEffect(() => {
    fetchDashboard();
    fetchMastery();
  }, [studentId]);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-6">学习仪表盘</h1>

      {loading && !dashboard && (
        <p className="text-gray-400">加载中...</p>
      )}
      {error && <p className="text-danger text-sm">{error}</p>}

      {dashboard && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mb-8">
          <div className="bg-white rounded-lg shadow p-5">
            <p className="text-gray-400 text-sm">累计作答</p>
            <p className="text-3xl font-bold text-primary-700">
              {dashboard.total_questions_attempted}
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-5">
            <p className="text-gray-400 text-sm">正确率</p>
            <p className="text-3xl font-bold text-success">
              {Math.round(dashboard.overall_accuracy * 100)}%
            </p>
          </div>
          <div className="bg-white rounded-lg shadow p-5">
            <p className="text-gray-400 text-sm">正确 / 总数</p>
            <p className="text-3xl font-bold">
              {dashboard.correct_count}
              <span className="text-gray-300 text-lg"> / {dashboard.total_questions_attempted}</span>
            </p>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Mastery chart */}
        <div className="bg-white rounded-lg shadow p-5">
          <h2 className="font-semibold mb-3">知识掌握度</h2>
          {mastery.length > 0 ? (
            <MasteryChart items={mastery} />
          ) : (
            <p className="text-gray-400 text-sm">
              {loading ? "加载中..." : "暂无数据。完成一次测验后即可查看。"}
            </p>
          )}
        </div>

        {/* Weak / Strong topics */}
        <div className="bg-white rounded-lg shadow p-5">
          <h2 className="font-semibold mb-3">知识点分析</h2>
          {dashboard && (
            <div className="space-y-4">
              <div>
                <p className="text-xs text-gray-400 mb-1">需加强</p>
                {dashboard.weak_topics.length > 0 ? (
                  dashboard.weak_topics.map((t) => (
                    <span
                      key={t}
                      className="inline-block bg-red-100 text-red-700 text-xs px-2 py-0.5 rounded mr-1 mb-1"
                    >
                      {t}
                    </span>
                  ))
                ) : (
                  <p className="text-xs text-gray-400">暂无薄弱知识点</p>
                )}
              </div>
              <div>
                <p className="text-xs text-gray-400 mb-1">优势领域</p>
                {dashboard.strong_topics.length > 0 ? (
                  dashboard.strong_topics.map((t) => (
                    <span
                      key={t}
                      className="inline-block bg-green-100 text-green-700 text-xs px-2 py-0.5 rounded mr-1 mb-1"
                    >
                      {t}
                    </span>
                  ))
                ) : (
                  <p className="text-xs text-gray-400">暂无优势知识点</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Quick actions */}
      <div className="mt-6 flex gap-3">
        <button
          className="bg-primary-600 text-white px-5 py-2 rounded text-sm hover:bg-primary-700"
          onClick={() => navigate("/materials")}
        >
          开始新测验
        </button>
        <button
          className="border border-primary-600 text-primary-600 px-5 py-2 rounded text-sm hover:bg-primary-50"
          onClick={() => navigate("/plan")}
        >
          查看今日计划
        </button>
      </div>
    </div>
  );
}
