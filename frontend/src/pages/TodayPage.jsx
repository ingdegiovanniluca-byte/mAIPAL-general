import React from "react";
import { useNavigate } from "react-router-dom";
import { LayoutDashboard } from "lucide-react";
import TodayDashboard from "@/components/TodayDashboard";
import { useIsMobile } from "@/hooks/use-is-mobile";

/* Dashboard (artigiano): the day at a glance. A commessa opens its diary, which goes back here. */
export default function TodayPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const open = (id) => navigate(`/dashboard/journal?commessa=${encodeURIComponent(id)}`, { state: { commessa: id, from: "dashboard" } });
  return (
    <div className="w-full max-w-[640px] mx-auto" data-testid="today-page">
      {!isMobile && (
        <div className="flex items-center gap-2 mb-4">
          <LayoutDashboard size={20} className="text-white/80" />
          <h1 className="text-2xl font-semibold text-white">Dashboard</h1>
        </div>
      )}
      <TodayDashboard onOpenCommessa={open} />
    </div>
  );
}
