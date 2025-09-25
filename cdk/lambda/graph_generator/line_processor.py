"""
Line processing and merging logic for P&ID graph processing.
Main orchestrator that coordinates different line merging strategies.
"""

import logging
from typing import List, Dict
from models import GraphNodeType, Junction
from graph_service import GraphService
from line_merging_strategies import AberrantLineMerger, GeometricContinuationMerger, LShapeMerger

logger = logging.getLogger()


class LineProcessor:
    """Handles line connection, merging, and consolidation logic"""
    
    def __init__(self, graph_service: GraphService, config: Dict = None):
        self.graph_service = graph_service
        self.config = config or {}
        
        # Initialize strategy classes
        self.aberrant_merger = AberrantLineMerger(graph_service, self.config)
        self.geometric_merger = GeometricContinuationMerger(graph_service, self.config)
        self.l_shape_merger = LShapeMerger(graph_service, self.config)
    
    def merge_lines_safely_iteratively(self):
        """Phase A: Run safe merging (aberrant + geometric) until convergence"""
        max_iterations = self.config.get('max_merge_iterations', 10)
        iteration = 0
        
        logger.info("Starting safe iterative line merging (Phase A)")
        
        while iteration < max_iterations:
            initial_line_count = self._count_line_nodes()
            logger.info(f"Safe merge iteration {iteration + 1}: Starting with {initial_line_count} lines")
            
            # Run safe merge cycle (aberrant + geometric only)
            self._run_safe_merge_iteration()
            
            final_line_count = self._count_line_nodes()
            logger.info(f"Safe merge iteration {iteration + 1}: Finished with {final_line_count} lines")
            
            # If no lines were merged, we've reached convergence
            if final_line_count == initial_line_count:
                logger.info(f"Safe merge convergence reached - no lines merged in iteration {iteration + 1}")
                break
                
            iteration += 1
        
        if iteration >= max_iterations:
            logger.warning(f"Safe merge max iterations ({max_iterations}) reached without convergence")
        else:
            logger.info(f"Safe iterative merging completed after {iteration + 1} iterations")
    
    def merge_l_shapes_with_protection_iteratively(self, l_junctions: List[Junction], t_junctions: List[Junction]):
        """Phase C: Run L-shape merging with T-junction protection until convergence"""
        max_iterations = self.config.get('max_merge_iterations', 10)
        iteration = 0
        
        logger.info("Starting L-shape merging with T-junction protection (Phase C)")
        
        while iteration < max_iterations:
            initial_line_count = self._count_line_nodes()
            logger.info(f"L-shape merge iteration {iteration + 1}: Starting with {initial_line_count} lines")
            
            # Run L-shape merge with protection
            self._run_l_shape_merge_iteration(l_junctions, t_junctions)
            
            final_line_count = self._count_line_nodes()
            logger.info(f"L-shape merge iteration {iteration + 1}: Finished with {final_line_count} lines")
            
            # If no lines were merged, we've reached convergence
            if final_line_count == initial_line_count:
                logger.info(f"L-shape merge convergence reached - no lines merged in iteration {iteration + 1}")
                break
                
            iteration += 1
        
        if iteration >= max_iterations:
            logger.warning(f"L-shape merge max iterations ({max_iterations}) reached without convergence")
        else:
            logger.info(f"L-shape iterative merging completed after {iteration + 1} iterations")
    
    def _run_safe_merge_iteration(self):
        """Run safe merge iteration (Phase A: aberrant + geometric only)"""
        logger.info("Running safe merge iteration")
        
        # Phase 1: Merge aberrant/collinear segments
        self.aberrant_merger.merge_aberrant_lines()
        
        # Phase 2: Merge geometric continuations
        self.geometric_merger.merge_geometric_continuations()
        
        # Skip L-shape merging in safe mode
    
    def _run_l_shape_merge_iteration(self, l_junctions: List[Junction], t_junctions: List[Junction]):
        """Run L-shape merge iteration with T-junction protection (Phase C)"""
        logger.info("Running L-shape merge iteration with T-junction protection")
        
        # Run L-shape merging with L-junctions and T-junction protection
        self.l_shape_merger.merge_l_shapes_with_protection(l_junctions, t_junctions)
    
    def _count_line_nodes(self) -> int:
        """Count the number of line nodes in the graph"""
        count = 0
        for node_id, data in self.graph_service.graph.nodes(data=True):
            if data['node_type'] == GraphNodeType.LINE and not data.get('virtual', False):
                count += 1
        return count
    
    # # Legacy methods for backwards compatibility with tests
    # def merge_aberrant_lines(self):
    #     """Delegate to aberrant merger strategy"""
    #     self.aberrant_merger.merge_aberrant_lines()
    
    # def merge_geometric_continuations(self):
    #     """Delegate to geometric continuation merger strategy"""
    #     self.geometric_merger.merge_geometric_continuations()
    
    # def _find_geometric_continuation_groups(self):
    #     """Delegate to geometric continuation merger strategy (for tests)"""
    #     return self.geometric_merger._find_geometric_continuation_groups()
