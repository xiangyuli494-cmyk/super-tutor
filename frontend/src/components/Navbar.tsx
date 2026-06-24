import { NavLink } from "react-router-dom";

const links = [
  { to: "/", label: "仪表盘" },
  { to: "/materials", label: "材料" },
  { to: "/plan", label: "今日计划" },
];

export default function Navbar() {
  return (
    <nav className="bg-primary-700 text-white shadow">
      <div className="max-w-5xl mx-auto px-4 flex items-center h-14 gap-6">
        <span className="font-bold text-lg mr-2">超级私教</span>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === "/"}
            className={({ isActive }) =>
              `text-sm transition ${
                isActive
                  ? "text-white border-b-2 border-white pb-1"
                  : "text-primary-200 hover:text-white"
              }`
            }
          >
            {l.label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}
