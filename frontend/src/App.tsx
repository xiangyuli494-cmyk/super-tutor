import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import MaterialsPage from "./pages/MaterialsPage";
import QuizPage from "./pages/QuizPage";
import ResultsPage from "./pages/ResultsPage";
import PlanPage from "./pages/PlanPage";

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/materials" element={<MaterialsPage />} />
        <Route path="/quiz/:sessionId" element={<QuizPage />} />
        <Route path="/quiz/:sessionId/results" element={<ResultsPage />} />
        <Route path="/plan" element={<PlanPage />} />
      </Routes>
    </Layout>
  );
}
