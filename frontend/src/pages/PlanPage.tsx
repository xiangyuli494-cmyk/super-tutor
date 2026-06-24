import { useEffect } from "react";
import { useStudentStore } from "../store/studentStore";

const activityLabels: Record<string, string> = {
  review: "复习",
  practice: "练习",
  quiz: "测验",
};

export default function PlanPage() {
  const { studentId, todayPlan, loading, error, fetchTodayPlan } =
    useStudentStore();

  useEffect(() => {
    fetchTodayPlan();
  }, [studentId]);

  return (
    <div>
      <h1 className="text-2xl font-bold mb-2">今日复习计划</h1>
      <p className="text-sm text-gray-500 mb-6">
        {todayPlan?.date || "—"} · 学生: {studentId}
      </p>

      {loading && <p className="text-gray-400">加载中...</p>}
      {error && <p className="text-danger text-sm">{error}</p>}

      {todayPlan && todayPlan.items.length > 0 ? (
        <div className="space-y-3">
          {todayPlan.items.map((item) => (
            <div
              key={item.item_id}
              className={`bg-white rounded-lg shadow p-4 flex items-center gap-4 ${
                item.completed ? "opacity-60" : ""
              }`}
            >
              <input
                type="checkbox"
                checked={item.completed}
                readOnly
                className="accent-primary-600"
              />
              <div className="flex-1">
                <p className="font-medium text-sm">
                  {activityLabels[item.activity_type] || item.activity_type}:{" "}
                  {item.knowledge_node_id}
                </p>
                {item.notes && (
                  <p className="text-xs text-gray-500 mt-1">{item.notes}</p>
                )}
              </div>
              <div className="text-right text-xs text-gray-400">
                <p>{item.estimated_minutes} 分钟</p>
              </div>
            </div>
          ))}
        </div>
      ) : (
        !loading && (
          <div className="bg-white rounded-lg shadow p-8 text-center">
            <p className="text-gray-400 mb-2">今日暂无排期</p>
            <p className="text-xs text-gray-400">
              完成一次测验并生成学习计划后即可查看每日复习清单
            </p>
          </div>
        )
      )}
    </div>
  );
}
