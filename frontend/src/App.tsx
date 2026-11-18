import { useEffect, useState } from "react";
import { NavLink, Route, Routes } from "react-router-dom";
import { api } from "./api";
import Banner from "./components/Banner";
import CaseList from "./pages/CaseList";
import CaseView from "./pages/CaseView";
import ListingsReference from "./pages/ListingsReference";
import Metrics from "./pages/Metrics";

export default function App() {
  const [me, setMe] = useState<{ name: string; role: string } | null>(null);
  useEffect(() => {
    api.get<{ name: string; role: string }>("/api/me").then(setMe).catch(() => setMe(null));
  }, []);
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-2 text-sm font-bold ${isActive ? "border-b-4 border-white" : "border-b-4 border-transparent hover:border-blue-200"}`;
  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-white focus:p-2">Skip to main content</a>
      <Banner />
      <header className="bg-[#162e51] text-white">
        <div className="flex flex-wrap items-center gap-4 px-4 py-2">
          <p className="text-lg font-bold">DDS Examiner Copilot</p>
          <nav aria-label="Primary" className="flex gap-1">
            <NavLink to="/" end className={link}>Cases</NavLink>
            <NavLink to="/metrics" className={link}>Pilot metrics</NavLink>
            <NavLink to="/reference" className={link}>Listings &amp; CAL reference</NavLink>
          </nav>
          <p className="ml-auto text-sm">{me ? `${me.name} · ${me.role}` : "Backend not reachable"}</p>
        </div>
      </header>
      <main id="main" className="flex-1">
        <Routes>
          <Route path="/" element={<CaseList />} />
          <Route path="/claims/:id" element={<CaseView />} />
          <Route path="/reference" element={<ListingsReference />} />
          <Route path="/metrics" element={<Metrics />} />
        </Routes>
      </main>
    </div>
  );
}
