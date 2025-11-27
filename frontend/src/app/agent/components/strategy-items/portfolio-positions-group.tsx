import { LineChart, Wallet } from "lucide-react";
import { type FC, memo } from "react";
import { ValueCellAgentPng } from "@/assets/png";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import MultiLineChart from "@/components/valuecell/charts/model-multi-line";
import { PngIcon } from "@/components/valuecell/png-icon";
import ScrollContainer from "@/components/valuecell/scroll/scroll-container";
import {
  formatChange,
  getChangeType,
  getCoinCapIcon,
  numberFixed,
} from "@/lib/utils";
import { useStockColors } from "@/store/settings-store";
import type {
  AccountInfo,
  PortfolioSummary,
  Position,
  StrategyAssets,
} from "@/types/strategy";

interface PortfolioPositionsGroupProps {
  priceCurve: Array<Array<number | string>>;
  positions: Position[];
  summary?: PortfolioSummary;
  assets?: StrategyAssets;
  accountInfo?: AccountInfo;
  exchangeId?: string;
  tradingMode?: "live" | "virtual";
}

interface PositionRowProps {
  position: Position;
}

const PositionRow: FC<PositionRowProps> = ({ position }) => {
  const stockColors = useStockColors();
  const changeType = getChangeType(position.unrealized_pnl);

  return (
    <TableRow>
      <TableCell>
        <div className="flex items-center gap-2">
          <PngIcon
            src={getCoinCapIcon(position.symbol)}
            callback={ValueCellAgentPng}
          />
          <p className="font-medium text-gray-950 text-sm">{position.symbol}</p>
        </div>
      </TableCell>
      <TableCell>
        <Badge
          variant="outline"
          className={
            position.type === "LONG" ? "text-rose-600" : "text-emerald-600"
          }
        >
          {position.type}
        </Badge>
      </TableCell>
      <TableCell>
        <p className="font-medium text-gray-950 text-sm">
          {position.leverage}X
        </p>
      </TableCell>
      <TableCell>
        <p className="font-medium text-gray-950 text-sm">{position.quantity}</p>
      </TableCell>
      <TableCell>
        <p
          className="font-medium text-sm"
          style={{ color: stockColors[changeType] }}
        >
          {formatChange(position.unrealized_pnl, "", 2)} (
          {formatChange(position.unrealized_pnl_pct, "", 2)}%)
        </p>
      </TableCell>
    </TableRow>
  );
};

const PortfolioPositionsGroup: FC<PortfolioPositionsGroupProps> = ({
  summary,
  priceCurve,
  positions,
  assets,
  accountInfo,
  exchangeId,
  tradingMode,
}) => {
  const stockColors = useStockColors();
  
  // Determine if we should use exchange account info data for Portfolio Value History
  // Priority: accountInfo (from /capi/v2/account/accounts) > assets (from /capi/v2/account/assets) > summary
  const hasAccountInfo = accountInfo && (accountInfo.total_equity > 0 || accountInfo.total_available > 0);
  const hasAssets = assets && assets.assets && assets.assets.length > 0;
  const isWeex = exchangeId?.toLowerCase() === "weex";
  
  // Calculate totals from exchange assets if accountInfo is not available
  let assetsTotalEquity = 0;
  let assetsAvailableBalance = 0;
  let assetsTotalPnl = 0;
  
  if (!hasAccountInfo && hasAssets && assets) {
    for (const asset of assets.assets) {
      const coinName = asset.coin_name.toUpperCase();
      // For Weex, focus on USDT/USD/USDC as quote currencies
      // For other exchanges, sum all assets
      if (isWeex) {
        // For Weex, sum USDT/USD/USDC assets
        if (coinName === "USDT" || coinName === "USD" || coinName === "USDC") {
          assetsTotalEquity += asset.equity || 0;
          assetsAvailableBalance += asset.available || 0;
          assetsTotalPnl += asset.unrealized_pnl || 0;
        }
      } else {
        // For other exchanges, sum all assets
        assetsTotalEquity += asset.equity || 0;
        assetsAvailableBalance += asset.available || 0;
        assetsTotalPnl += asset.unrealized_pnl || 0;
      }
    }
  }
  
  // Use accountInfo if available (from /capi/v2/account/accounts), otherwise use assets or summary
  const useAccountInfo = hasAccountInfo;
  const useAssetsData = !hasAccountInfo && hasAssets && (assetsTotalEquity > 0 || assetsAvailableBalance > 0);
  
  const displayTotalEquity = useAccountInfo 
    ? (accountInfo?.total_equity ?? 0)
    : (useAssetsData ? assetsTotalEquity : (summary?.total_value ?? 0));
  const displayAvailableBalance = useAccountInfo
    ? (accountInfo?.total_available ?? 0)
    : (useAssetsData ? assetsAvailableBalance : (summary?.cash ?? 0));
  // For P&L, accountInfo doesn't have it directly, so calculate from positions or use summary
  const displayTotalPnl = useAssetsData ? assetsTotalPnl : (summary?.total_pnl ?? 0);
  
  const changeType = getChangeType(displayTotalPnl ?? 0);

  const hasPositions = positions.length > 0;
  const hasPriceCurve = priceCurve.length > 0;

  // When using exchange account info or assets data, add current data point to price curve
  // to ensure the chart shows the latest value matching the displayed metrics
  const useExchangeData = useAccountInfo || useAssetsData;
  const enhancedPriceCurve = useExchangeData && displayTotalEquity > 0
    ? (() => {
        // Clone the price curve array
        const curve = priceCurve.length > 0 ? [...priceCurve] : [];
        
        // Get current timestamp in the same format as backend (YYYY-MM-DD HH:MM:SS)
        const now = new Date();
        const timeStr = now.toISOString().slice(0, 19).replace('T', ' ');
        
        if (curve.length === 0) {
          // No existing curve data, create new curve with current point
          return [
            ['Time', 'Portfolio Value'],
            [timeStr, displayTotalEquity],
          ];
        }
        
        // Find if there's already a data point for current time (within same minute)
        const currentMinute = timeStr.slice(0, 16); // YYYY-MM-DD HH:MM
        let existingIndex = -1;
        
        for (let i = 1; i < curve.length; i++) {
          const rowTime = String(curve[i][0]).slice(0, 16);
          if (rowTime === currentMinute) {
            existingIndex = i;
            break;
          }
        }
        
        if (existingIndex > 0) {
          // Update existing point with latest value
          curve[existingIndex] = [timeStr, displayTotalEquity];
        } else {
          // Add new point at the end (maintain chronological order)
          // Find the right position to insert (keep sorted by time)
          let insertIndex = curve.length;
          for (let i = 1; i < curve.length; i++) {
            const rowTime = String(curve[i][0]);
            if (rowTime > timeStr) {
              insertIndex = i;
              break;
            }
          }
          curve.splice(insertIndex, 0, [timeStr, displayTotalEquity]);
        }
        
        return curve;
      })()
    : priceCurve;

  const hasEnhancedPriceCurve = enhancedPriceCurve.length > 0;

  return (
    <div className="flex flex-1 flex-col gap-8 overflow-y-scroll p-6">
      {/* Portfolio Value History Section */}
      <div className="flex flex-1 flex-col gap-4">
        <h3 className="font-semibold text-base text-gray-950">
          Portfolio Value History
        </h3>

        <div className="grid grid-cols-3 gap-4 text-nowrap">
          <div className="rounded-lg bg-gray-50 p-4">
            <p className="text-gray-500 text-sm">Total Equity</p>
            <p className="mt-1 font-semibold text-gray-900 text-lg">
              {numberFixed(displayTotalEquity, 4)}
            </p>
            {useExchangeData && exchangeId && (
              <p className="mt-1 text-gray-400 text-xs">From {exchangeId.toUpperCase()}</p>
            )}
          </div>
          <div className="rounded-lg bg-gray-50 p-4">
            <p className="text-gray-500 text-sm">Available Balance</p>
            <p className="mt-1 font-semibold text-gray-900 text-lg">
              {numberFixed(displayAvailableBalance, 4)}
            </p>
            {useExchangeData && exchangeId && (
              <p className="mt-1 text-gray-400 text-xs">From {exchangeId.toUpperCase()}</p>
            )}
          </div>
          <div className="rounded-lg bg-gray-50 p-4">
            <p className="text-gray-500 text-sm">Total P&L</p>
            <p
              className="mt-1 font-semibold text-gray-900 text-lg"
              style={{ color: stockColors[changeType] }}
            >
              {numberFixed(displayTotalPnl, 4)}
            </p>
            {useExchangeData && exchangeId && (
              <p className="mt-1 text-gray-400 text-xs">From {exchangeId.toUpperCase()}</p>
            )}
          </div>
        </div>

        <div className="min-h-[400px] flex-1">
          {hasEnhancedPriceCurve ? (
            <MultiLineChart data={enhancedPriceCurve} showLegend={false} />
          ) : (
            <div className="flex h-full items-center justify-center rounded-xl bg-gray-50">
              <div className="flex flex-col items-center gap-4 px-6 py-12 text-center">
                <div className="flex size-14 items-center justify-center rounded-full bg-gray-100">
                  <LineChart className="size-7 text-gray-400" />
                </div>
                <div className="flex flex-col gap-2">
                  <p className="font-semibold text-base text-gray-700">
                    No portfolio value data
                  </p>
                  <p className="max-w-xs text-gray-500 text-sm leading-relaxed">
                    Portfolio value chart will appear once trading begins
                  </p>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Positions Section */}
      <div className="flex flex-col gap-4">
        <h3 className="font-semibold text-base text-gray-950">Positions</h3>
        {hasPositions ? (
          <ScrollContainer className="max-h-[260px]">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>
                    <p className="font-normal text-gray-400 text-sm">Symbol</p>
                  </TableHead>
                  <TableHead>
                    <p className="font-normal text-gray-400 text-sm">Type</p>
                  </TableHead>
                  <TableHead>
                    <p className="font-normal text-gray-400 text-sm">
                      Leverage
                    </p>
                  </TableHead>
                  <TableHead>
                    <p className="font-normal text-gray-400 text-sm">
                      Quantity
                    </p>
                  </TableHead>
                  <TableHead>
                    <p className="font-normal text-gray-400 text-sm">P&L</p>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positions.map((position, index) => (
                  <PositionRow
                    key={`${position.symbol}-${index}`}
                    position={position}
                  />
                ))}
              </TableBody>
            </Table>
          </ScrollContainer>
        ) : (
          <div className="flex min-h-[240px] items-center justify-center rounded-xl bg-gray-50">
            <div className="flex flex-col items-center gap-4 px-6 py-10 text-center">
              <div className="flex size-12 items-center justify-center rounded-full bg-gray-100">
                <Wallet className="size-6 text-gray-400" />
              </div>
              <div className="flex flex-col gap-1.5">
                <p className="font-semibold text-gray-700 text-sm">
                  No open positions
                </p>
                <p className="max-w-xs text-gray-500 text-xs leading-relaxed">
                  Positions will appear here when trades are opened
                </p>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default memo(PortfolioPositionsGroup);
